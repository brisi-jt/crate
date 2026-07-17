"""New-category (queue-cluster) suggestion.

Rides the M1 202 + background-compute + AnalyticsSnapshot infra: UMAP/HDBSCAN
NEVER runs in the request path (P1-1). The read path returns the cached proposal
or `pending`; the background path computes over a BOUNDED sample of the queue
(ceiling well under the crash threshold) and stores it keyed on source+filter+
content hash.
"""

import pytest
from sqlmodel import Session

from crate.model.enums import FeatureStatus
from crate.model.orm import SavedTrack, Track, TrackFeatures, User
from crate.services.triage import cluster as cluster_mod
from crate.services.triage.cluster import (
    queue_content_hash,
    read_cluster_proposal,
)
from crate.services.triage.queue import QueueSource

pytestmark = pytest.mark.unit


def _track(session: Session, sid: str, feats: dict) -> int:
    row = Track(
        spotify_id=sid, name=f"Track {sid}", artists=[{"spotify_id": f"a-{sid}", "name": "A"}]
    )
    session.add(row)
    session.flush()
    assert row.id is not None
    session.add(TrackFeatures(track_id=row.id, status=FeatureStatus.present, **feats))
    return row.id


HI = {"energy": 0.9, "valence": 0.8, "acousticness": 0.1}
LO = {"energy": 0.1, "valence": 0.2, "acousticness": 0.9}


def _liked_queue_of(session: Session, user: User, n: int) -> list[int]:
    ids = []
    for i in range(n):
        feats = HI if i % 2 == 0 else LO
        tid = _track(session, f"t{i}", feats)
        session.add(SavedTrack(user_id=user.id, track_id=tid))
        ids.append(tid)
    session.commit()
    return ids


# -- content hash --------------------------------------------------------------


def test_content_hash_changes_with_track_set() -> None:
    a = queue_content_hash(QueueSource(liked=True, max_playlists=0), [1, 2, 3])
    b = queue_content_hash(QueueSource(liked=True, max_playlists=0), [1, 2, 4])
    same = queue_content_hash(QueueSource(liked=True, max_playlists=0), [3, 2, 1])
    assert a != b
    assert a == same  # order-independent


def test_content_hash_changes_with_source() -> None:
    a = queue_content_hash(QueueSource(liked=True, max_playlists=0), [1, 2])
    b = queue_content_hash(QueueSource(liked=True, max_playlists=1), [1, 2])
    c = queue_content_hash(QueueSource(playlist_id=5), [1, 2])
    assert len({a, b, c}) == 3


# -- read path never computes (P1-1) -------------------------------------------


def test_read_cold_returns_pending_without_computing(
    session: Session, user: User, monkeypatch
) -> None:
    _liked_queue_of(session, user, 12)
    called = {"compute": False}

    def _boom(*_a, **_k):
        called["compute"] = True
        raise AssertionError("compute_track_map must never run in the read path")

    monkeypatch.setattr(cluster_mod, "compute_track_map", _boom)

    result = read_cluster_proposal(session, user, QueueSource(liked=True, max_playlists=0))
    assert result.status == "pending"
    assert called["compute"] is False


def test_read_below_floor_is_empty_state(session: Session, user: User) -> None:
    _liked_queue_of(session, user, 4)  # below MIN_TRACKS_FOR_MAP (10)
    result = read_cluster_proposal(session, user, QueueSource(liked=True, max_playlists=0))
    assert result.status == "empty"
    assert result.proposals == []


# -- background compute + warm read --------------------------------------------


def test_precompute_then_warm_read_returns_proposals(session: Session, user: User) -> None:
    _liked_queue_of(session, user, 16)
    src = QueueSource(liked=True, max_playlists=0)

    cluster_mod.precompute_triage_cluster(session, user, src)
    result = read_cluster_proposal(session, user, src)

    assert result.status == "ready"
    # Each proposal names founding members and a suggested name.
    for p in result.proposals:
        assert p.founding_track_ids
        assert p.suggested_name


def test_precompute_caps_clustered_set(session: Session, user: User, monkeypatch) -> None:
    """The clustered sample is bounded well under the crash threshold, even for
    a huge Liked-mode N=0 queue (P1-1)."""
    _liked_queue_of(session, user, 40)
    captured = {"n": None}

    real = cluster_mod.compute_track_map

    def _spy(matrix, track_ids, memberships):
        captured["n"] = matrix.shape[0]
        return real(matrix, track_ids, memberships)

    monkeypatch.setattr(cluster_mod, "MAX_CLUSTER_SAMPLE", 20)
    monkeypatch.setattr(cluster_mod, "compute_track_map", _spy)

    cluster_mod.precompute_triage_cluster(session, user, QueueSource(liked=True, max_playlists=0))
    assert captured["n"] is not None
    assert captured["n"] <= 20  # capped


def test_stale_snapshot_recomputes(session: Session, user: User) -> None:
    """A snapshot whose content hash no longer matches the queue is treated as
    a miss (pending), not served stale."""
    ids = _liked_queue_of(session, user, 16)
    src = QueueSource(liked=True, max_playlists=0)
    cluster_mod.precompute_triage_cluster(session, user, src)
    assert read_cluster_proposal(session, user, src).status == "ready"

    # Queue changes: add a new saved track -> content hash moves.
    new = _track(session, "new", HI)
    session.add(SavedTrack(user_id=user.id, track_id=new))
    session.commit()
    _ = ids

    assert read_cluster_proposal(session, user, src).status == "pending"
