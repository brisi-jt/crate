"""Recently-played capture — idempotent upsert across overlapping windows."""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from crate.model.orm import PlayEvent, User
from crate.services.account.plays import capture_recent_plays
from crate.services.spotify.models import PlayContext, PlayHistoryItem, SpotifyTrack

pytestmark = pytest.mark.unit


def play(spotify_id: str, played_at: datetime, context: PlayContext | None = None):
    return PlayHistoryItem(
        played_at=played_at,
        track=SpotifyTrack.model_validate(
            {
                "id": spotify_id,
                "name": f"Track {spotify_id}",
                "artists": [{"id": f"artist-{spotify_id}", "name": f"Artist {spotify_id}"}],
            }
        ),
        context=context,
    )


class FakePlaysReader:
    def __init__(self, items: list[PlayHistoryItem]) -> None:
        self.items = items

    async def get_recently_played(self, limit: int = 50) -> list[PlayHistoryItem]:
        return self.items[:limit]


async def test_first_capture_stores_all_plays(session: Session, user: User) -> None:
    reader = FakePlaysReader(
        [
            play("t1", datetime(2026, 7, 12, 10, 0, 0, 123000)),
            play(
                "t2",
                datetime(2026, 7, 12, 9, 30),
                context=PlayContext(type="playlist", uri="spotify:playlist:pl1"),
            ),
        ]
    )

    report = await capture_recent_plays(session, reader, user)

    assert report.captured == 2
    assert report.duplicates == 0
    rows = session.exec(select(PlayEvent).where(PlayEvent.user_id == user.id)).all()
    assert len(rows) == 2
    by_time = {row.played_at: row for row in rows}
    assert by_time[datetime(2026, 7, 12, 9, 30)].context_type == "playlist"
    assert by_time[datetime(2026, 7, 12, 9, 30)].context_uri == "spotify:playlist:pl1"
    assert by_time[datetime(2026, 7, 12, 10, 0, 0, 123000)].context_type is None


async def test_overlapping_window_dedupes_on_played_at(session: Session, user: User) -> None:
    first = [play("t1", datetime(2026, 7, 12, 10, 0)), play("t2", datetime(2026, 7, 12, 9, 30))]
    await capture_recent_plays(session, FakePlaysReader(first), user)

    # The next poll's 50-item window overlaps the previous one.
    overlap = [play("t3", datetime(2026, 7, 12, 10, 30)), *first]
    report = await capture_recent_plays(session, FakePlaysReader(overlap), user)

    assert report.captured == 1
    assert report.duplicates == 2
    rows = session.exec(select(PlayEvent).where(PlayEvent.user_id == user.id)).all()
    assert len(rows) == 3


async def test_replaying_the_same_track_at_different_times_is_two_plays(
    session: Session, user: User
) -> None:
    reader = FakePlaysReader(
        [play("t1", datetime(2026, 7, 12, 10, 0)), play("t1", datetime(2026, 7, 12, 9, 0))]
    )

    report = await capture_recent_plays(session, reader, user)

    assert report.captured == 2
    rows = session.exec(select(PlayEvent).where(PlayEvent.user_id == user.id)).all()
    assert len(rows) == 2
    assert rows[0].track_id == rows[1].track_id


async def test_ghost_tracks_are_skipped(session: Session, user: User) -> None:
    item = PlayHistoryItem(
        played_at=datetime(2026, 7, 12, 10, 0),
        track=SpotifyTrack.model_validate({"id": None, "name": "ghost"}),
    )

    report = await capture_recent_plays(session, FakePlaysReader([item]), user)

    assert report.captured == 0
    assert session.exec(select(PlayEvent)).all() == []
