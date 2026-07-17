"""New-category (queue-cluster) suggestion for the triage panel.

Clusters the CURRENT triage queue and proposes a playlist per dense cluster
(suggested name from the cluster's dominant genres/feature character, founding
members listed). The panel always shows this, quiet unless existing fit is weak.

P1-1 — this must NEVER recreate the map crash in the request path:

- UMAP/HDBSCAN runs only in ``precompute_triage_cluster`` (a background task,
  same 202 pattern as the track map), never in ``read_cluster_proposal``.
- The clustered set is capped at ``MAX_CLUSTER_SAMPLE`` (a bounded sample well
  under the crash threshold) — a Liked-mode N=0 queue can be thousands of
  tracks.
- The proposal is cached in the ``triage_cluster`` AnalyticsSnapshot keyed on
  the queue source; the payload carries a content hash of (source + filter +
  track-id set) so a moved queue reads as a miss (pending) and recomputes,
  rather than serving a stale proposal.
"""

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
from sqlmodel import Session, col, select

from crate.model.enums import FeatureStatus, SnapshotKind
from crate.model.orm import AnalyticsSnapshot, Genre, Track, TrackFeatures, User
from crate.model.orm.base import utcnow
from crate.services.analytics.clustering import (
    MIN_TRACKS_FOR_MAP,
    clustering_features,
    compute_track_map,
)
from crate.services.analytics.loaders import (
    GENRE_CLUSTER_WEIGHT,
    load_genre_vectors,
    load_percentile_space,
)
from crate.services.analytics.percentiles import PercentileSpace
from crate.services.enrichment.calibration import CALIBRATED_FEATURES
from crate.services.triage.queue import QueueSource, load_queue

# Ceiling on the clustered sample. UMAP is O(n log n)-ish but the real hazard is
# an unbounded request-time compute; this keeps every cluster pass small and
# deterministic. Well under the size that crashed the in-request map path.
MAX_CLUSTER_SAMPLE = 400

# How many tracks read to form the queue for clustering (a bounded window even
# for a huge Liked-mode N=0 queue).
_QUEUE_WINDOW = 2000


@dataclass
class ClusterProposal:
    suggested_name: str
    founding_track_ids: list[int]
    size: int


@dataclass
class ClusterResult:
    # "ready" (proposals cached), "pending" (background compute scheduled/needed),
    # "empty" (queue below the clustering floor — quiet state).
    status: str
    proposals: list[ClusterProposal] = field(default_factory=list)


def _source_key(source: QueueSource) -> dict[str, object]:
    return {
        "playlist_id": source.playlist_id,
        "liked": source.liked,
        "max_playlists": source.max_playlists,
    }


def queue_content_hash(source: QueueSource, track_ids: list[int]) -> str:
    """Stable hash of the queue's source + filter + track-id SET (order-free)."""
    payload = {"source": _source_key(source), "tracks": sorted(set(track_ids))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _snapshot_playlist_id(source: QueueSource) -> int | None:
    return source.playlist_id  # null for Liked mode


def _read_snapshot_row(
    session: Session, user: User, source: QueueSource
) -> AnalyticsSnapshot | None:
    assert user.id is not None
    return session.exec(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.user_id == user.id)
        .where(AnalyticsSnapshot.kind == SnapshotKind.triage_cluster)
        .where(AnalyticsSnapshot.playlist_id == _snapshot_playlist_id(source))
    ).first()


def _queue_track_ids(session: Session, user: User, source: QueueSource) -> list[int]:
    assert user.id is not None
    result = load_queue(session, user.id, source, limit=_QUEUE_WINDOW, offset=0)
    return [entry.track_id for entry in result.items]


def read_cluster_proposal(session: Session, user: User, source: QueueSource) -> ClusterResult:
    """Serve the cached proposal, or say why not — NEVER computes UMAP/HDBSCAN.

    Returns empty below the clustering floor, ready when a fresh snapshot exists,
    pending otherwise (the endpoint schedules the background compute).
    """
    track_ids = _queue_track_ids(session, user, source)
    if len(track_ids) < MIN_TRACKS_FOR_MAP:
        return ClusterResult(status="empty")

    content_hash = queue_content_hash(source, track_ids)
    row = _read_snapshot_row(session, user, source)
    if row is None or row.payload.get("content_hash") != content_hash:
        return ClusterResult(status="pending")

    proposals = [
        ClusterProposal(
            suggested_name=p["suggested_name"],
            founding_track_ids=p["founding_track_ids"],
            size=p["size"],
        )
        for p in row.payload.get("proposals", [])
    ]
    return ClusterResult(status="ready", proposals=proposals)


def precompute_triage_cluster(session: Session, user: User, source: QueueSource) -> None:
    """Background compute: cluster the queue and cache the proposal.

    Bounded sample, deterministic. A no-op below the clustering floor. Upserts
    the single triage_cluster snapshot row for this source.
    """
    assert user.id is not None
    track_ids = _queue_track_ids(session, user, source)
    if len(track_ids) < MIN_TRACKS_FOR_MAP:
        return

    content_hash = queue_content_hash(source, track_ids)
    sample = track_ids[:MAX_CLUSTER_SAMPLE]

    space = load_percentile_space(session)
    cluster_feats = clustering_features(space.features)
    vectors = _load_vectors(session, sample, space)
    aligned = [tid for tid in sample if tid in vectors]
    if len(aligned) < MIN_TRACKS_FOR_MAP:
        proposals: list[dict] = []
    else:
        matrix = np.array(
            [[vectors[tid][f] for f in cluster_feats] for tid in aligned], dtype=float
        ).reshape(len(aligned), len(cluster_feats))
        # G3: blend genre into the queue's cluster distance too, so the
        # new-category proposal is genre-legible (matches the track map).
        genre_vectors, genre_names = load_genre_vectors(session, aligned)
        genre_matrix = None
        if genre_names:
            genre_matrix = (
                np.array([genre_vectors[tid] for tid in aligned], dtype=float).reshape(
                    len(aligned), len(genre_names)
                )
                * GENRE_CLUSTER_WEIGHT
            )
        # No playlist memberships needed — the queue itself is the population.
        result = compute_track_map(matrix, aligned, {}, genre_matrix=genre_matrix)
        proposals = _proposals_from_result(session, result) if result else []

    payload = {
        "content_hash": content_hash,
        "source": _source_key(source),
        "proposals": proposals,
    }
    _upsert_snapshot(session, user, source, payload)


def _load_vectors(
    session: Session, track_ids: list[int], space: PercentileSpace
) -> dict[int, dict[str, float]]:
    rows = session.exec(
        select(TrackFeatures)
        .where(TrackFeatures.status == FeatureStatus.present)
        .where(col(TrackFeatures.track_id).in_(track_ids))
    ).all()
    vectors: dict[int, dict[str, float]] = {}
    for row in rows:
        vectors[row.track_id] = space.transform({f: getattr(row, f) for f in CALIBRATED_FEATURES})
    return vectors


def _proposals_from_result(session: Session, result) -> list[dict]:
    """One proposal per non-noise cluster: {suggested name, founding members}."""
    by_cluster: dict[int, list[int]] = {}
    for point in result.points:
        if point.cluster == -1:
            continue
        by_cluster.setdefault(point.cluster, []).append(point.track_id)

    proposals: list[dict] = []
    for cluster in sorted(by_cluster, key=lambda c: (-len(by_cluster[c]), c)):
        members = by_cluster[cluster]
        proposals.append(
            {
                "suggested_name": _suggest_name(session, members),
                "founding_track_ids": members,
                "size": len(members),
            }
        )
    return proposals


def _suggest_name(session: Session, track_ids: list[int]) -> str:
    """Name a cluster from its dominant ENAO genre, falling back to a generic."""
    tracks = session.exec(select(Track).where(col(Track.id).in_(track_ids))).all()
    artist_keys = {
        str(credit.get("name", "")).casefold()
        for track in tracks
        for credit in track.artists
        if credit.get("name")
    }
    if artist_keys:
        from crate.model.orm import ArtistGenre

        rows = session.exec(
            select(Genre.name, ArtistGenre.weight)
            .join(ArtistGenre, ArtistGenre.genre_id == Genre.id)  # type: ignore[arg-type]
            .where(col(ArtistGenre.artist_name).in_(list(artist_keys)))
        ).all()
        tally: dict[str, float] = {}
        for name, weight in rows:
            tally[name] = tally.get(name, 0.0) + float(weight or 0.0)
        if tally:
            top = max(tally.items(), key=lambda kv: kv[1])[0]
            return top.title()
    return f"New cluster · {len(track_ids)} tracks"


def _upsert_snapshot(session: Session, user: User, source: QueueSource, payload: dict) -> None:
    assert user.id is not None
    row = _read_snapshot_row(session, user, source)
    if row is None:
        row = AnalyticsSnapshot(
            user_id=user.id,
            kind=SnapshotKind.triage_cluster,
            playlist_id=_snapshot_playlist_id(source),
            owned_only=True,
            payload=payload,
            computed_at=utcnow(),
        )
    else:
        row.payload = payload
        row.computed_at = utcnow()
    session.add(row)
    session.commit()
