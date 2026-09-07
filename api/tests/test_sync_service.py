"""Sync engine unit tests.

Fixture-pair pattern: run a first sync against remote state A to establish the
baseline, swap the fake Spotify to state B, run again, and assert on exactly
the SyncEvents and membership changes the delta implies.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from crate.model.enums import PlaylistSyncStatus, SyncEventSource, SyncEventType
from crate.model.orm import Artist, Playlist, PlaylistTrack, SyncEvent, Track, User
from crate.services.spotify.models import (
    PlaylistTrackItem,
    SpotifyAlbumRef,
    SpotifyArtistRef,
    SpotifyExternalIds,
    SpotifyOwner,
    SpotifyPlaylistSummary,
    SpotifyTrack,
    SpotifyTracksRef,
)
from crate.services.sync import SyncService

pytestmark = pytest.mark.unit


def remote_playlist(
    pid: str,
    name: str,
    snapshot: str,
    owner: str = "spotify-jt",
    total: int = 0,
) -> SpotifyPlaylistSummary:
    return SpotifyPlaylistSummary(
        id=pid,
        name=name,
        snapshot_id=snapshot,
        owner=SpotifyOwner(id=owner),
        tracks=SpotifyTracksRef(total=total),
    )


def remote_track(tid: str, name: str | None = None, artist: str | None = None) -> PlaylistTrackItem:
    artist_name = artist or f"Artist {tid}"
    return PlaylistTrackItem(
        added_at=datetime(2026, 1, 1, tzinfo=UTC),
        track=SpotifyTrack(
            id=tid,
            name=name or f"Track {tid}",
            duration_ms=200_000,
            external_ids=SpotifyExternalIds(isrc=f"ISRC{tid[:8].upper()}"),
            artists=[SpotifyArtistRef(id=f"artist-{artist_name}", name=artist_name)],
            album=SpotifyAlbumRef(id=f"album-{tid}", name=f"Album {tid}"),
        ),
    )


class FakeSpotify:
    """In-memory stand-in for SpotifyClient's read surface."""

    def __init__(
        self,
        playlists: list[SpotifyPlaylistSummary],
        tracks: dict[str, list[PlaylistTrackItem]],
    ) -> None:
        self.playlists = playlists
        self.tracks = tracks
        self.track_fetches: list[str] = []

    async def iter_playlists(self) -> AsyncIterator[SpotifyPlaylistSummary]:
        for playlist in self.playlists:
            yield playlist

    async def iter_playlist_tracks(self, playlist_id: str) -> AsyncIterator[PlaylistTrackItem]:
        self.track_fetches.append(playlist_id)
        for item in self.tracks.get(playlist_id, []):
            yield item


async def run_sync(session: Session, user: User, fake: FakeSpotify):
    return await SyncService(session=session, spotify=fake, user=user).run()


def events(session: Session, event_type: SyncEventType | None = None) -> list[SyncEvent]:
    statement = select(SyncEvent)
    if event_type is not None:
        statement = statement.where(SyncEvent.event_type == event_type)
    return list(session.exec(statement).all())


def membership(session: Session, playlist: Playlist) -> list[tuple[str, int]]:
    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.playlist_id == playlist.id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(PlaylistTrack.position)
    ).all()
    return [(track.spotify_id, pt.position) for pt, track in rows]


BASELINE_PLAYLISTS = [remote_playlist("pl-1", "night drives", "snap-1", total=3)]
BASELINE_TRACKS = {"pl-1": [remote_track("t-a"), remote_track("t-b"), remote_track("t-c")]}


async def establish_baseline(session: Session, user: User) -> None:
    fake = FakeSpotify(list(BASELINE_PLAYLISTS), dict(BASELINE_TRACKS))
    await run_sync(session, user, fake)


# --- first sync -------------------------------------------------------------


async def test_first_sync_creates_playlists_tracks_and_created_events(
    session: Session, user: User
) -> None:
    fake = FakeSpotify(
        [
            remote_playlist("pl-1", "night drives", "snap-1", total=2),
            remote_playlist("pl-2", "followed mix", "snap-9", owner="other-user", total=1),
        ],
        {
            "pl-1": [remote_track("t-a"), remote_track("t-b")],
            "pl-2": [remote_track("t-b")],
        },
    )
    report = await run_sync(session, user, fake)

    playlists = list(session.exec(select(Playlist)).all())
    assert {p.spotify_id for p in playlists} == {"pl-1", "pl-2"}
    owned = {p.spotify_id: p.is_owned for p in playlists}
    assert owned == {"pl-1": True, "pl-2": False}
    assert all(p.status == PlaylistSyncStatus.synced for p in playlists)
    assert all(p.last_synced_at is not None for p in playlists)
    assert all(p.user_id == user.id for p in playlists)

    created = events(session, SyncEventType.playlist_created)
    assert len(created) == 2
    assert all(e.source == SyncEventSource.sync for e in created)
    # First observation is the baseline — no per-track `added` flood.
    assert events(session, SyncEventType.added) == []

    # t-b appears in both playlists but is a single global row.
    tracks = list(session.exec(select(Track)).all())
    assert {t.spotify_id for t in tracks} == {"t-a", "t-b"}

    artists = list(session.exec(select(Artist)).all())
    assert {a.name for a in artists} == {"Artist t-a", "Artist t-b"}

    assert report.playlists_created == 2


async def test_first_sync_persists_positions_and_isrc(session: Session, user: User) -> None:
    await establish_baseline(session, user)
    playlist = session.exec(select(Playlist)).one()
    assert membership(session, playlist) == [("t-a", 0), ("t-b", 1), ("t-c", 2)]
    track = session.exec(select(Track).where(Track.spotify_id == "t-a")).one()
    assert track.isrc == "ISRCT-A"
    assert track.artists == [{"spotify_id": "artist-Artist t-a", "name": "Artist t-a"}]


# --- diff sync: the fixture pairs -------------------------------------------


async def test_added_track_emits_exactly_one_added_event(session: Session, user: User) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(
        [remote_playlist("pl-1", "night drives", "snap-2", total=4)],
        {"pl-1": BASELINE_TRACKS["pl-1"] + [remote_track("t-d")]},
    )
    report = await run_sync(session, user, fake)

    added = events(session, SyncEventType.added)
    assert len(added) == 1
    new_track = session.exec(select(Track).where(Track.spotify_id == "t-d")).one()
    assert added[0].track_id == new_track.id
    assert events(session, SyncEventType.removed) == []
    assert events(session, SyncEventType.reordered) == []

    playlist = session.exec(select(Playlist)).one()
    assert playlist.snapshot_id == "snap-2"
    assert membership(session, playlist) == [("t-a", 0), ("t-b", 1), ("t-c", 2), ("t-d", 3)]
    assert report.tracks_added == 1


async def test_removed_track_emits_exactly_one_removed_event(session: Session, user: User) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(
        [remote_playlist("pl-1", "night drives", "snap-2", total=2)],
        {"pl-1": [remote_track("t-a"), remote_track("t-c")]},
    )
    report = await run_sync(session, user, fake)

    removed = events(session, SyncEventType.removed)
    assert len(removed) == 1
    gone = session.exec(select(Track).where(Track.spotify_id == "t-b")).one()
    assert removed[0].track_id == gone.id
    assert events(session, SyncEventType.added) == []

    playlist = session.exec(select(Playlist)).one()
    assert membership(session, playlist) == [("t-a", 0), ("t-c", 1)]
    assert report.tracks_removed == 1


async def test_reorder_only_emits_single_reordered_event(session: Session, user: User) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(
        [remote_playlist("pl-1", "night drives", "snap-2", total=3)],
        {"pl-1": [remote_track("t-c"), remote_track("t-a"), remote_track("t-b")]},
    )
    await run_sync(session, user, fake)

    reordered = events(session, SyncEventType.reordered)
    assert len(reordered) == 1
    assert reordered[0].track_id is None
    assert events(session, SyncEventType.added) == []
    assert events(session, SyncEventType.removed) == []

    playlist = session.exec(select(Playlist)).one()
    assert membership(session, playlist) == [("t-c", 0), ("t-a", 1), ("t-b", 2)]


async def test_add_and_remove_does_not_emit_reordered(session: Session, user: User) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(
        [remote_playlist("pl-1", "night drives", "snap-2", total=3)],
        {"pl-1": [remote_track("t-b"), remote_track("t-a"), remote_track("t-d")]},
    )
    await run_sync(session, user, fake)

    assert len(events(session, SyncEventType.added)) == 1
    assert len(events(session, SyncEventType.removed)) == 1
    # Position churn from add/remove is implied; a reordered event would be noise.
    assert events(session, SyncEventType.reordered) == []


async def test_duplicate_occurrence_of_same_track_counts_as_added(
    session: Session, user: User
) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(
        [remote_playlist("pl-1", "night drives", "snap-2", total=4)],
        {"pl-1": BASELINE_TRACKS["pl-1"] + [remote_track("t-a")]},
    )
    await run_sync(session, user, fake)

    added = events(session, SyncEventType.added)
    assert len(added) == 1
    playlist = session.exec(select(Playlist)).one()
    assert membership(session, playlist) == [("t-a", 0), ("t-b", 1), ("t-c", 2), ("t-a", 3)]


async def test_rename_only_emits_renamed_and_skips_track_fetch(
    session: Session, user: User
) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(
        [remote_playlist("pl-1", "midnight drives", "snap-1", total=3)],
        dict(BASELINE_TRACKS),
    )
    report = await run_sync(session, user, fake)

    renamed = events(session, SyncEventType.playlist_renamed)
    assert len(renamed) == 1
    assert renamed[0].detail == {"from": "night drives", "to": "midnight drives"}
    assert fake.track_fetches == []  # snapshot unchanged — membership not refetched

    playlist = session.exec(select(Playlist)).one()
    assert playlist.name == "midnight drives"
    assert report.playlists_renamed == 1
    assert events(session, SyncEventType.added) == []


async def test_deleted_playlist_marks_and_emits(session: Session, user: User) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify([], {})
    report = await run_sync(session, user, fake)

    deleted = events(session, SyncEventType.playlist_deleted)
    assert len(deleted) == 1
    playlist = session.exec(select(Playlist)).one()
    assert playlist.is_deleted is True
    assert deleted[0].playlist_id == playlist.id
    # Membership history is retained for time travel.
    assert len(membership(session, playlist)) == 3
    assert report.playlists_deleted == 1


async def test_deleted_playlist_not_reported_again(session: Session, user: User) -> None:
    await establish_baseline(session, user)
    await run_sync(session, user, FakeSpotify([], {}))
    await run_sync(session, user, FakeSpotify([], {}))
    assert len(events(session, SyncEventType.playlist_deleted)) == 1


async def test_unchanged_snapshot_skips_entirely(session: Session, user: User) -> None:
    await establish_baseline(session, user)

    fake = FakeSpotify(list(BASELINE_PLAYLISTS), dict(BASELINE_TRACKS))
    report = await run_sync(session, user, fake)

    all_events = events(session)
    assert [e.event_type for e in all_events] == [SyncEventType.playlist_created]
    assert fake.track_fetches == []
    assert report.playlists_skipped == 1


async def test_null_and_local_tracks_are_skipped(session: Session, user: User) -> None:
    ghost = PlaylistTrackItem(added_at=None, track=None)
    local = PlaylistTrackItem(
        added_at=None,
        track=SpotifyTrack(id=None, name="Local File", is_local=True),
    )
    fake = FakeSpotify(
        [remote_playlist("pl-1", "with ghosts", "snap-1", total=3)],
        {"pl-1": [ghost, local, remote_track("t-a")]},
    )
    await run_sync(session, user, fake)

    playlist = session.exec(select(Playlist)).one()
    assert membership(session, playlist) == [("t-a", 0)]


# --- empty-fetch guard: protect existing membership on transient Spotify failure ---


async def test_empty_spotify_response_preserves_existing_membership(
    session: Session, user: User
) -> None:
    """Regression: if Spotify returns 0 tracks for an established playlist,
    _refresh_membership must bail out early rather than deleting all rows.

    This guards against transient throttling or network errors that return an
    empty iterator — a scenario that previously wiped the PlaylistTrack history
    without raising an exception (so no rollback ever fired).
    """
    # Establish baseline with 3 tracks.
    await establish_baseline(session, user)
    playlist = session.exec(select(Playlist)).one()
    assert len(membership(session, playlist)) == 3

    # Second sync: Spotify returns a new snapshot but zero tracks — simulates a
    # transient throttle / empty-response error right after re-auth.
    fake = FakeSpotify(
        [remote_playlist("pl-1", "night drives", "snap-2", total=3)],
        {"pl-1": []},  # empty — Spotify returned nothing
    )
    await run_sync(session, user, fake)

    # The guard must have fired: all 3 existing rows survive.
    session.expire_all()
    assert membership(session, playlist) == [("t-a", 0), ("t-b", 1), ("t-c", 2)]
    # No membership-change events should have been emitted.
    assert events(session, SyncEventType.added) == []
    assert events(session, SyncEventType.removed) == []
