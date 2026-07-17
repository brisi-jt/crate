"""Snapshot cache behavior: read-through, invalidation, and the sync hook."""

import pytest
from sqlmodel import Session, select

from crate.model.enums import SnapshotKind
from crate.model.orm import AnalyticsSnapshot, User
from crate.services.analytics.snapshots import get_or_compute, invalidate_snapshots
from crate.services.sync import SyncService
from tests.test_sync_service import FakeSpotify, remote_playlist, remote_track

pytestmark = pytest.mark.unit


def test_get_or_compute_computes_once(session: Session, user: User) -> None:
    calls = {"count": 0}

    def compute() -> dict:
        calls["count"] += 1
        return {"value": 42}

    first = get_or_compute(session, user, SnapshotKind.graph, compute)
    second = get_or_compute(session, user, SnapshotKind.graph, compute)
    assert first == second == {"value": 42}
    assert calls["count"] == 1


def test_playlist_scope_separates_snapshots(session: Session, user: User) -> None:
    get_or_compute(session, user, SnapshotKind.flow, lambda: {"p": 1}, playlist_id=1)
    get_or_compute(session, user, SnapshotKind.flow, lambda: {"p": 2}, playlist_id=2)
    assert get_or_compute(session, user, SnapshotKind.flow, dict, playlist_id=1) == {"p": 1}
    assert get_or_compute(session, user, SnapshotKind.flow, dict, playlist_id=2) == {"p": 2}


def test_owned_scope_separates_snapshots(session: Session, user: User) -> None:
    get_or_compute(session, user, SnapshotKind.graph, lambda: {"scope": "owned"})
    get_or_compute(session, user, SnapshotKind.graph, lambda: {"scope": "all"}, owned_only=False)
    assert get_or_compute(session, user, SnapshotKind.graph, dict) == {"scope": "owned"}
    assert get_or_compute(session, user, SnapshotKind.graph, dict, owned_only=False) == {
        "scope": "all"
    }
    rows = session.exec(select(AnalyticsSnapshot)).all()
    assert {row.owned_only for row in rows} == {True, False}


def test_invalidate_scoped_to_user(session: Session, user: User) -> None:
    other = User(clerk_user_id="other-user")
    session.add(other)
    session.commit()
    session.refresh(other)

    get_or_compute(session, user, SnapshotKind.graph, lambda: {"u": 1})
    get_or_compute(session, other, SnapshotKind.graph, lambda: {"u": 2})

    removed = invalidate_snapshots(session, user.id)
    session.commit()
    assert removed == 1
    remaining = session.exec(select(AnalyticsSnapshot)).all()
    assert [row.user_id for row in remaining] == [other.id]


def test_invalidate_without_user_clears_everything(session: Session, user: User) -> None:
    get_or_compute(session, user, SnapshotKind.graph, lambda: {"u": 1})
    get_or_compute(session, user, SnapshotKind.temporal, lambda: {"u": 1})
    removed = invalidate_snapshots(session)
    session.commit()
    assert removed == 2
    assert session.exec(select(AnalyticsSnapshot)).all() == []


def test_invalidate_kinds_drops_only_named_kinds(session: Session, user: User) -> None:
    get_or_compute(session, user, SnapshotKind.graph, lambda: {"k": "graph"})
    get_or_compute(session, user, SnapshotKind.track_map, lambda: {"k": "track_map"})
    get_or_compute(session, user, SnapshotKind.temporal, lambda: {"k": "temporal"})

    removed = invalidate_snapshots(
        session, user.id, kinds=[SnapshotKind.graph, SnapshotKind.temporal]
    )
    session.commit()

    assert removed == 2
    remaining = session.exec(select(AnalyticsSnapshot)).all()
    assert {row.kind for row in remaining} == {SnapshotKind.track_map}


async def test_sync_with_changes_invalidates_snapshots(session: Session, user: User) -> None:
    get_or_compute(session, user, SnapshotKind.graph, lambda: {"stale": True})

    spotify = FakeSpotify(
        playlists=[remote_playlist("pl-1", "Fresh", "snap-1", total=1)],
        tracks={"pl-1": [remote_track("t-1")]},
    )
    await SyncService(session=session, spotify=spotify, user=user).run()

    assert session.exec(select(AnalyticsSnapshot)).all() == []


async def test_noop_sync_keeps_snapshots_warm(session: Session, user: User) -> None:
    spotify = FakeSpotify(
        playlists=[remote_playlist("pl-1", "Fresh", "snap-1", total=1)],
        tracks={"pl-1": [remote_track("t-1")]},
    )
    await SyncService(session=session, spotify=spotify, user=user).run()

    get_or_compute(session, user, SnapshotKind.graph, lambda: {"warm": True})
    # Second pass sees the same snapshot_id everywhere — nothing changed.
    await SyncService(session=session, spotify=spotify, user=user).run()

    rows = session.exec(select(AnalyticsSnapshot)).all()
    assert len(rows) == 1 and rows[0].payload == {"warm": True}
