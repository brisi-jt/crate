"""Triage queue assembly.

The queue is the set of tracks awaiting a filing decision, in inbox order.

Two sources:

- **Playlist**: the source playlist's tracks, ``added_at`` ascending —
  oldest-waiting first, a true inbox.
- **Liked Songs**: saved (not-removed) tracks filtered to those appearing in
  ``<= max_playlists`` live owned playlists (the ≤N slider; default 0 =
  orphans). P0-4: the ≤N filter is pushed into SQL via a per-track live
  membership count, so ``total`` and page boundaries are correct at every N —
  never applied in Python after pagination.
"""

from dataclasses import dataclass, field

from sqlalchemy import func
from sqlmodel import Session, col, select

from crate.model.orm import Playlist, PlaylistTrack, SavedTrack, Track


@dataclass(frozen=True)
class QueueSource:
    """Which source the queue draws from.

    Exactly one of ``playlist_id`` / ``liked`` is set. ``max_playlists`` is the
    ≤N slider, only meaningful in Liked mode.
    """

    playlist_id: int | None = None
    liked: bool = False
    max_playlists: int = 0


@dataclass(frozen=True)
class QueueEntry:
    track_id: int
    spotify_id: str
    name: str


@dataclass
class QueueResult:
    items: list[QueueEntry] = field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


def _live_membership_count_subquery(user_id: int):
    """Per-track count of LIVE owned-playlist memberships (soft-deleted excluded)."""
    return (
        select(
            col(PlaylistTrack.track_id).label("track_id"),
            func.count(func.distinct(col(PlaylistTrack.playlist_id))).label("cnt"),
        )
        .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user_id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
        .group_by(col(PlaylistTrack.track_id))
        .subquery()
    )


def load_queue(
    session: Session,
    user_id: int,
    source: QueueSource,
    *,
    limit: int = 50,
    offset: int = 0,
) -> QueueResult:
    if source.playlist_id is not None:
        return _playlist_queue(session, user_id, source.playlist_id, limit=limit, offset=offset)
    return _liked_queue(session, user_id, source.max_playlists, limit=limit, offset=offset)


def _playlist_queue(
    session: Session, user_id: int, playlist_id: int, *, limit: int, offset: int
) -> QueueResult:
    base = (
        select(PlaylistTrack, Track)
        .join(Track, Track.id == PlaylistTrack.track_id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user_id)
        .where(PlaylistTrack.playlist_id == playlist_id)
    )
    total = session.exec(
        select(func.count())
        .select_from(PlaylistTrack)
        .where(PlaylistTrack.user_id == user_id)
        .where(PlaylistTrack.playlist_id == playlist_id)
    ).one()
    rows = session.exec(
        base.order_by(col(PlaylistTrack.added_at).asc(), col(PlaylistTrack.position).asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return QueueResult(
        items=[
            QueueEntry(track_id=track.id, spotify_id=track.spotify_id, name=track.name)
            for _pt, track in rows
            if track.id is not None
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


def _liked_queue(
    session: Session, user_id: int, max_playlists: int, *, limit: int, offset: int
) -> QueueResult:
    counts = _live_membership_count_subquery(user_id)

    # LEFT JOIN so a saved track in ZERO live playlists (count NULL -> 0)
    # qualifies at N=0. The ≤N filter runs in SQL, before pagination.
    membership = func.coalesce(counts.c.cnt, 0)
    filtered = (
        select(SavedTrack, Track)
        .join(Track, Track.id == SavedTrack.track_id)  # type: ignore[arg-type]
        .join(counts, counts.c.track_id == SavedTrack.track_id, isouter=True)
        .where(SavedTrack.user_id == user_id)
        .where(SavedTrack.is_removed == False)  # noqa: E712 — SQL expression
        .where(membership <= max_playlists)
    )

    total_stmt = (
        select(func.count())
        .select_from(SavedTrack)
        .join(counts, counts.c.track_id == SavedTrack.track_id, isouter=True)
        .where(SavedTrack.user_id == user_id)
        .where(SavedTrack.is_removed == False)  # noqa: E712 — SQL expression
        .where(membership <= max_playlists)
    )
    total = session.exec(total_stmt).one()

    rows = session.exec(
        filtered.order_by(col(SavedTrack.saved_at).asc(), col(SavedTrack.id).asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return QueueResult(
        items=[
            QueueEntry(track_id=track.id, spotify_id=track.spotify_id, name=track.name)
            for _saved, track in rows
            if track.id is not None
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )
