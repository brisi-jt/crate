"""Sync must never reset a playlist's triage_excluded flag.

The account marks a playlist excluded from triage; the nightly Spotify sync
upserts that same playlist row (a rename, a membership change, a plain
re-observation). None of those may touch triage_excluded — the exclusion is a
crate-native preference, not a Spotify fact. A fresh playlist Spotify has never
shown before is eligible (default false).
"""

import pytest
from sqlmodel import Session, select

from crate.model.orm import Playlist, User
from tests.test_sync_service import (
    FakeSpotify,
    remote_playlist,
    remote_track,
    run_sync,
)

pytestmark = pytest.mark.unit


async def test_sync_preserves_triage_excluded_across_reobservation(
    session: Session, user: User
) -> None:
    # First sync creates the playlist.
    fake = FakeSpotify(
        [remote_playlist("pl-1", "gym", "snap-1", total=1)],
        {"pl-1": [remote_track("t-a")]},
    )
    await run_sync(session, user, fake)

    # The account holds it out of triage.
    row = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-1")).one()
    row.triage_excluded = True
    session.add(row)
    session.commit()

    # A second sync re-observes it (rename + a membership change so both the
    # snapshot-skip and the refresh path run) — the exclusion must survive.
    fake2 = FakeSpotify(
        [remote_playlist("pl-1", "GYM (renamed)", "snap-2", total=2)],
        {"pl-1": [remote_track("t-a"), remote_track("t-b")]},
    )
    await run_sync(session, user, fake2)

    row = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-1")).one()
    assert row.name == "GYM (renamed)"  # the sync did update the row
    assert row.triage_excluded is True  # …but not this


async def test_sync_preserves_triage_excluded_when_snapshot_unchanged(
    session: Session, user: User
) -> None:
    fake = FakeSpotify(
        [remote_playlist("pl-1", "gym", "snap-1", total=1)],
        {"pl-1": [remote_track("t-a")]},
    )
    await run_sync(session, user, fake)

    row = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-1")).one()
    row.triage_excluded = True
    session.add(row)
    session.commit()

    # Same snapshot id -> the membership-refresh path is skipped entirely.
    await run_sync(session, user, fake)

    row = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-1")).one()
    assert row.triage_excluded is True


async def test_newly_synced_playlist_is_eligible(session: Session, user: User) -> None:
    fake = FakeSpotify(
        [remote_playlist("pl-new", "fresh", "snap-1", total=1)],
        {"pl-new": [remote_track("t-a")]},
    )
    await run_sync(session, user, fake)

    row = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-new")).one()
    assert row.triage_excluded is False
