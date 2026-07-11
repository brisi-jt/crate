"""AnalyticsSnapshot cache: read-through storage plus invalidation.

Kept separate from the engine so the sync and enrichment services can
invalidate cached analytics without importing numpy/umap machinery.
"""

from collections.abc import Callable
from typing import Any

from sqlmodel import Session, delete, select

from crate.model.enums import SnapshotKind
from crate.model.orm import AnalyticsSnapshot, User
from crate.model.orm.base import utcnow


def get_or_compute(
    session: Session,
    user: User,
    kind: SnapshotKind,
    compute: Callable[[], dict[str, Any]],
    playlist_id: int | None = None,
    owned_only: bool = True,
) -> dict[str, Any]:
    """Serve the cached payload for (user, kind, playlist, scope) or compute and store it.

    owned_only is part of the cache key: the same kind computed over owned
    playlists and over the full library are different payloads.
    """
    assert user.id is not None
    row = session.exec(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.user_id == user.id)
        .where(AnalyticsSnapshot.kind == kind)
        .where(AnalyticsSnapshot.playlist_id == playlist_id)
        .where(AnalyticsSnapshot.owned_only == owned_only)
    ).first()
    if row is not None:
        return row.payload

    payload = compute()
    session.add(
        AnalyticsSnapshot(
            user_id=user.id,
            kind=kind,
            playlist_id=playlist_id,
            owned_only=owned_only,
            payload=payload,
            computed_at=utcnow(),
        )
    )
    session.commit()
    return payload


def invalidate_snapshots(session: Session, user_id: int | None = None) -> int:
    """Drop cached analytics — for one user, or for everyone when global data
    (track features) changed. Returns the number of rows removed. The caller
    owns the commit."""
    statement = delete(AnalyticsSnapshot)
    if user_id is not None:
        statement = statement.where(AnalyticsSnapshot.user_id == user_id)  # type: ignore[attr-defined]
    result = session.exec(statement)  # type: ignore[call-overload]
    return int(result.rowcount or 0)
