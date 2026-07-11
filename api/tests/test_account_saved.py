"""Saved-tracks diff sync — full walk vs stored library, add/remove trail."""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from crate.model.orm import SavedTrack, Track, User
from crate.services.account.saved import sync_saved_tracks
from crate.services.spotify.models import SavedTrackItem, SpotifyTrack

pytestmark = pytest.mark.unit


def remote_track(spotify_id: str, name: str | None = None) -> SpotifyTrack:
    return SpotifyTrack.model_validate(
        {
            "id": spotify_id,
            "name": name or f"Track {spotify_id}",
            "duration_ms": 200_000,
            "external_ids": {"isrc": f"ISRC{spotify_id.upper()}"},
            "artists": [{"id": f"artist-{spotify_id}", "name": f"Artist {spotify_id}"}],
            "album": {"id": f"album-{spotify_id}", "name": "Album"},
        }
    )


class FakeSavedReader:
    """Yields a scripted saved-tracks listing, newest first like Spotify."""

    def __init__(self, items: list[tuple[str, datetime | None]]) -> None:
        self.items = items

    async def iter_saved_tracks(self):
        for spotify_id, added_at in self.items:
            yield SavedTrackItem(added_at=added_at, track=remote_track(spotify_id))


def saved_rows(session: Session, user: User) -> dict[str, SavedTrack]:
    rows = session.exec(
        select(SavedTrack, Track)
        .where(SavedTrack.user_id == user.id)
        .where(SavedTrack.track_id == Track.id)
    ).all()
    return {track.spotify_id: saved for saved, track in rows}


async def test_first_walk_records_all_as_saved(session: Session, user: User) -> None:
    reader = FakeSavedReader([("t1", datetime(2026, 7, 1)), ("t2", datetime(2026, 6, 1))])

    report = await sync_saved_tracks(session, reader, user)

    assert report.added == 2
    assert report.removed == 0
    assert report.total_saved == 2
    rows = saved_rows(session, user)
    assert set(rows) == {"t1", "t2"}
    assert rows["t1"].saved_at == datetime(2026, 7, 1)
    assert rows["t1"].is_removed is False
    # Track catalog rows were upserted through the shared helper.
    track = session.exec(select(Track).where(Track.spotify_id == "t1")).one()
    assert track.isrc == "ISRCT1"


async def test_second_walk_is_idempotent(session: Session, user: User) -> None:
    reader = FakeSavedReader([("t1", datetime(2026, 7, 1))])
    await sync_saved_tracks(session, reader, user)

    report = await sync_saved_tracks(session, reader, user)

    assert report.added == 0
    assert report.removed == 0
    assert report.total_saved == 1
    assert len(saved_rows(session, user)) == 1


async def test_unsave_flips_removed_and_keeps_row(session: Session, user: User) -> None:
    await sync_saved_tracks(
        session,
        FakeSavedReader([("t1", datetime(2026, 7, 1)), ("t2", datetime(2026, 6, 1))]),
        user,
    )

    report = await sync_saved_tracks(session, FakeSavedReader([("t1", datetime(2026, 7, 1))]), user)

    assert report.removed == 1
    rows = saved_rows(session, user)
    assert rows["t2"].is_removed is True
    assert rows["t2"].removed_at is not None
    assert rows["t1"].is_removed is False


async def test_resave_reactivates_the_same_row(session: Session, user: User) -> None:
    await sync_saved_tracks(session, FakeSavedReader([("t1", datetime(2026, 6, 1))]), user)
    await sync_saved_tracks(session, FakeSavedReader([]), user)

    report = await sync_saved_tracks(session, FakeSavedReader([("t1", datetime(2026, 7, 5))]), user)

    assert report.added == 1
    rows = saved_rows(session, user)
    assert len(rows) == 1  # reactivated, not duplicated
    assert rows["t1"].is_removed is False
    assert rows["t1"].removed_at is None
    assert rows["t1"].saved_at == datetime(2026, 7, 5)


async def test_local_file_entries_are_skipped(session: Session, user: User) -> None:
    class ReaderWithLocalFile(FakeSavedReader):
        async def iter_saved_tracks(self):
            yield SavedTrackItem(
                added_at=datetime(2026, 7, 1),
                track=SpotifyTrack.model_validate({"id": None, "name": "local file"}),
            )
            yield SavedTrackItem(added_at=datetime(2026, 7, 1), track=remote_track("t1"))

    report = await sync_saved_tracks(session, ReaderWithLocalFile([]), user)

    assert report.added == 1
    assert set(saved_rows(session, user)) == {"t1"}
