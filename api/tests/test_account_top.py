"""Top-items snapshot capture — all six kind x range combos in one pass."""

import pytest
from sqlmodel import Session, select

from crate.model.enums import TopItemKind, TopTimeRange
from crate.model.orm import TopItemsSnapshot, User
from crate.services.account.top import capture_top_items
from crate.services.spotify.models import SpotifyTopArtist, SpotifyTrack

pytestmark = pytest.mark.unit


class FakeTopReader:
    """Returns range-labelled items so tests can pin the range→row mapping."""

    def __init__(self) -> None:
        self.requested: list[tuple[str, str]] = []

    async def get_top_artists(self, time_range: str, limit: int = 50) -> list[SpotifyTopArtist]:
        self.requested.append(("artists", time_range))
        return [SpotifyTopArtist(id=f"artist-{time_range}", name=f"Top Artist {time_range}")]

    async def get_top_tracks(self, time_range: str, limit: int = 50) -> list[SpotifyTrack]:
        self.requested.append(("tracks", time_range))
        return [
            SpotifyTrack.model_validate(
                {
                    "id": f"track-{time_range}",
                    "name": f"Top Track {time_range}",
                    "artists": [{"id": "a1", "name": "Artist One"}],
                }
            ),
            SpotifyTrack.model_validate(
                {
                    "id": f"track2-{time_range}",
                    "name": f"Second Track {time_range}",
                    "artists": [{"id": "a2", "name": "Artist Two"}],
                }
            ),
        ]


async def test_capture_writes_all_six_combos(session: Session, user: User) -> None:
    reader = FakeTopReader()

    report = await capture_top_items(session, reader, user)

    assert report.snapshots == 6
    rows = session.exec(select(TopItemsSnapshot).where(TopItemsSnapshot.user_id == user.id)).all()
    assert len(rows) == 6
    combos = {(row.kind, row.time_range) for row in rows}
    assert combos == {(k, r) for k in TopItemKind for r in TopTimeRange}
    # One pass shares a single captured_at across all six rows.
    assert len({row.captured_at for row in rows}) == 1
    # The Spotify API ranges were requested with their _term suffixes.
    assert ("artists", "short_term") in reader.requested
    assert ("tracks", "long_term") in reader.requested


async def test_items_are_ranked_and_carry_names(session: Session, user: User) -> None:
    await capture_top_items(session, FakeTopReader(), user)

    track_row = session.exec(
        select(TopItemsSnapshot)
        .where(TopItemsSnapshot.kind == TopItemKind.track)
        .where(TopItemsSnapshot.time_range == TopTimeRange.medium)
    ).one()
    assert track_row.items == [
        {
            "rank": 1,
            "spotify_id": "track-medium_term",
            "name": "Top Track medium_term",
            "artists": ["Artist One"],
        },
        {
            "rank": 2,
            "spotify_id": "track2-medium_term",
            "name": "Second Track medium_term",
            "artists": ["Artist Two"],
        },
    ]

    artist_row = session.exec(
        select(TopItemsSnapshot)
        .where(TopItemsSnapshot.kind == TopItemKind.artist)
        .where(TopItemsSnapshot.time_range == TopTimeRange.short)
    ).one()
    assert artist_row.items == [
        {"rank": 1, "spotify_id": "artist-short_term", "name": "Top Artist short_term"}
    ]


async def test_repeat_captures_append_history(session: Session, user: User) -> None:
    await capture_top_items(session, FakeTopReader(), user)
    await capture_top_items(session, FakeTopReader(), user)

    rows = session.exec(select(TopItemsSnapshot).where(TopItemsSnapshot.user_id == user.id)).all()
    assert len(rows) == 12  # snapshots are history, never overwritten
