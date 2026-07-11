"""Recently-played capture.

Polls Spotify's rolling 50-play window and appends unseen plays. Spotify
timestamps each play uniquely per user, so (user_id, played_at) makes the
capture idempotent across overlapping windows.
"""

from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session, select

from crate.model.orm import PlayEvent, Track, User
from crate.services.sync import _naive_utc, upsert_track


class RecentPlaysReader(Protocol):
    """Read surface of SpotifyClient the play capture depends on."""

    async def get_recently_played(self, limit: int = 50): ...  # list[PlayHistoryItem]


@dataclass
class RecentPlaysReport:
    """Counts from one recently-played capture."""

    captured: int = 0
    duplicates: int = 0


async def capture_recent_plays(
    session: Session, spotify: RecentPlaysReader, user: User
) -> RecentPlaysReport:
    report = RecentPlaysReport()
    items = await spotify.get_recently_played(limit=50)
    playable = [item for item in items if item.track.id is not None]
    if not playable:
        return report

    window_start = min(_naive_utc(item.played_at) for item in playable)
    existing = set(
        session.exec(
            select(PlayEvent.played_at)
            .where(PlayEvent.user_id == user.id)
            .where(PlayEvent.played_at >= window_start)
        ).all()
    )

    cache: dict[str, Track] = {}
    for item in playable:
        played_at = _naive_utc(item.played_at)
        if played_at in existing:
            report.duplicates += 1
            continue
        track = upsert_track(session, item.track, cache)
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=track.id,
                played_at=played_at,
                context_type=item.context.type if item.context else None,
                context_uri=item.context.uri if item.context else None,
            )
        )
        existing.add(played_at)
        report.captured += 1

    session.commit()
    return report
