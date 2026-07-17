"""AnalyticsSnapshot cache: read-through storage plus invalidation.

Kept separate from the engine so the sync and enrichment services can
invalidate cached analytics without importing numpy/umap machinery.
"""

from collections.abc import Callable, Collection
from typing import Any

from sqlmodel import Session, col, delete, select

from crate.model.enums import SnapshotKind
from crate.model.orm import AnalyticsSnapshot, User
from crate.model.orm.base import utcnow

# Snapshot kinds whose payload depends only on the enriched track set and its
# features — NOT on playlist membership. A membership-only mutation leaves
# these untouched so the triage ritual's rapid applies don't storm the
# expensive UMAP/HDBSCAN recompute. Enrichment (which changes features)
# and sync (which changes the track set) still evict everything.
MEMBERSHIP_INDEPENDENT_KINDS: frozenset[SnapshotKind] = frozenset({SnapshotKind.track_map})

# The kinds a membership-only mutation evicts: everything except the ones above.
MEMBERSHIP_MUTATION_KINDS: tuple[SnapshotKind, ...] = tuple(
    kind for kind in SnapshotKind if kind not in MEMBERSHIP_INDEPENDENT_KINDS
)


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


def read_snapshot(
    session: Session,
    user: User,
    kind: SnapshotKind,
    playlist_id: int | None = None,
    owned_only: bool = True,
) -> dict[str, Any] | None:
    """The cached payload for (user, kind, playlist, scope), or None — never computes.

    The 202-on-cold-cache endpoints use this instead of get_or_compute so an
    expensive payload (the track map) is never built in the request path.
    """
    assert user.id is not None
    row = session.exec(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.user_id == user.id)
        .where(AnalyticsSnapshot.kind == kind)
        .where(AnalyticsSnapshot.playlist_id == playlist_id)
        .where(AnalyticsSnapshot.owned_only == owned_only)
    ).first()
    return row.payload if row is not None else None


def invalidate_snapshots(
    session: Session,
    user_id: int | None = None,
    kinds: Collection[SnapshotKind] | None = None,
) -> int:
    """Drop cached analytics — for one user, or for everyone when global data
    (track features) changed.

    ``kinds`` restricts the drop to the named snapshot kinds; None drops every
    kind (the right thing when the track set or features moved). Membership-only
    mutations pass ``MEMBERSHIP_MUTATION_KINDS`` so the membership-independent
    track_map survives. Returns the number of rows removed. The caller owns the
    commit.
    """
    statement = delete(AnalyticsSnapshot)
    if user_id is not None:
        statement = statement.where(AnalyticsSnapshot.user_id == user_id)  # type: ignore[attr-defined]
    if kinds is not None:
        statement = statement.where(col(AnalyticsSnapshot.kind).in_(list(kinds)))  # type: ignore[attr-defined]
    result = session.exec(statement)  # type: ignore[call-overload]
    return int(result.rowcount or 0)
