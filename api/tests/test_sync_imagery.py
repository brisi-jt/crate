"""G6 imagery: the sync mapper persists album art + playlist covers.

Spotify already ships these URLs in the objects sync fetches; earlier syncs
discarded them. These tests pin that the mapper now writes image_url /
image_url_sm onto tracks and image_url onto playlists, choosing the largest
image as the anchor and the smallest as the thumb.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from crate.model.orm import Playlist, Track, User
from crate.services.spotify.models import (
    PlaylistTrackItem,
    SpotifyAlbumRef,
    SpotifyArtistRef,
    SpotifyImage,
    SpotifyOwner,
    SpotifyPlaylistSummary,
    SpotifyTrack,
    SpotifyTracksRef,
)
from crate.services.sync import SyncService

pytestmark = pytest.mark.unit


def _images() -> list[SpotifyImage]:
    # Spotify orders images largest-first, but the mapper must not rely on that.
    return [
        SpotifyImage(url="https://img/large.jpg", height=640, width=640),
        SpotifyImage(url="https://img/mid.jpg", height=300, width=300),
        SpotifyImage(url="https://img/small.jpg", height=64, width=64),
    ]


def _track_with_art(tid: str) -> PlaylistTrackItem:
    return PlaylistTrackItem(
        added_at=datetime(2026, 1, 1, tzinfo=UTC),
        track=SpotifyTrack(
            id=tid,
            name=f"Track {tid}",
            duration_ms=200_000,
            artists=[SpotifyArtistRef(id=f"artist-{tid}", name=f"Artist {tid}")],
            album=SpotifyAlbumRef(id=f"album-{tid}", name=f"Album {tid}", images=_images()),
        ),
    )


def _playlist_with_cover(pid: str) -> SpotifyPlaylistSummary:
    return SpotifyPlaylistSummary(
        id=pid,
        name="covered",
        snapshot_id="snap-1",
        owner=SpotifyOwner(id="spotify-jt"),
        tracks=SpotifyTracksRef(total=1),
        images=_images(),
    )


class _FakeSpotify:
    def __init__(
        self,
        playlists: list[SpotifyPlaylistSummary],
        tracks: dict[str, list[PlaylistTrackItem]],
    ) -> None:
        self.playlists = playlists
        self.tracks = tracks

    async def iter_playlists(self) -> AsyncIterator[SpotifyPlaylistSummary]:
        for playlist in self.playlists:
            yield playlist

    async def iter_playlist_tracks(self, playlist_id: str) -> AsyncIterator[PlaylistTrackItem]:
        for item in self.tracks.get(playlist_id, []):
            yield item


async def test_sync_persists_album_art_on_track(session: Session, user: User) -> None:
    fake = _FakeSpotify(
        [_playlist_with_cover("pl-1")],
        {"pl-1": [_track_with_art("t-a")]},
    )
    await SyncService(session=session, spotify=fake, user=user).run()

    track = session.exec(select(Track).where(Track.spotify_id == "t-a")).one()
    # Largest image is the anchor, smallest is the thumb.
    assert track.image_url == "https://img/large.jpg"
    assert track.image_url_sm == "https://img/small.jpg"


async def test_sync_persists_playlist_cover(session: Session, user: User) -> None:
    fake = _FakeSpotify(
        [_playlist_with_cover("pl-1")],
        {"pl-1": [_track_with_art("t-a")]},
    )
    await SyncService(session=session, spotify=fake, user=user).run()

    playlist = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-1")).one()
    assert playlist.image_url == "https://img/large.jpg"


async def test_sync_tolerates_missing_images(session: Session, user: User) -> None:
    fake = _FakeSpotify(
        [
            SpotifyPlaylistSummary(
                id="pl-1",
                name="bare",
                snapshot_id="snap-1",
                owner=SpotifyOwner(id="spotify-jt"),
                tracks=SpotifyTracksRef(total=1),
            )
        ],
        {
            "pl-1": [
                PlaylistTrackItem(
                    added_at=None,
                    track=SpotifyTrack(
                        id="t-a",
                        name="no art",
                        album=SpotifyAlbumRef(id="album-a", name="Album a"),
                    ),
                )
            ]
        },
    )
    await SyncService(session=session, spotify=fake, user=user).run()

    track = session.exec(select(Track).where(Track.spotify_id == "t-a")).one()
    playlist = session.exec(select(Playlist).where(Playlist.spotify_id == "pl-1")).one()
    assert track.image_url is None and track.image_url_sm is None
    assert playlist.image_url is None
