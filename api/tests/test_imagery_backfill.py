"""G6 imagery backfill: album art (via /albums) and artist photos (via /artists).

Both backfills must be idempotent — a second run selects nothing and writes
nothing — and must go through the SpotifyClient (whose _request already backs
off on 429), never a raw HTTP path that would sidestep the rate limiter. These
tests pin both properties offline with a fake client.
"""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from crate.model.orm import Artist, Playlist, PlaylistTrack, Track, User
from crate.services.imagery import backfill_album_art, backfill_artist_images
from crate.services.spotify.models import SpotifyArtist, SpotifyImage

pytestmark = pytest.mark.unit


class FakeImageClient:
    """Stand-in for SpotifyClient's image-fetch surface.

    Records every call so tests can assert the backfill only fetches what it
    needs (idempotency) and never exceeds the batch caps (rate-limiter
    discipline: one batched request stands in for one rate-limited call).
    """

    _ALBUMS_BATCH = 20
    _ARTISTS_BATCH = 50

    def __init__(
        self,
        albums: dict[str, list[dict]] | None = None,
        artists: dict[str, list[dict]] | None = None,
    ) -> None:
        self._albums = albums or {}
        self._artists = artists or {}
        self.album_batches: list[list[str]] = []
        self.artist_batches: list[list[str]] = []

    async def get_albums(self, album_ids: list[str]) -> list[dict]:
        assert len(album_ids) <= self._ALBUMS_BATCH, "album batch cap exceeded"
        self.album_batches.append(list(album_ids))
        return [
            {"id": aid, "images": self._albums[aid]} for aid in album_ids if aid in self._albums
        ]

    async def get_artists(self, artist_ids: list[str]) -> list[SpotifyArtist]:
        assert len(artist_ids) <= self._ARTISTS_BATCH, "artist batch cap exceeded"
        self.artist_batches.append(list(artist_ids))
        return [
            SpotifyArtist(
                id=aid,
                name=f"Artist {aid}",
                images=[SpotifyImage(**img) for img in self._artists[aid]],
            )
            for aid in artist_ids
            if aid in self._artists
        ]


def _images() -> list[dict]:
    return [
        {"url": "https://img/large.jpg", "height": 640, "width": 640},
        {"url": "https://img/small.jpg", "height": 64, "width": 64},
    ]


def _seed_owned_track(session: Session, user: User, *, spotify_id: str, album_id: str) -> Track:
    track = Track(spotify_id=spotify_id, name=f"Track {spotify_id}", album_spotify_id=album_id)
    session.add(track)
    session.flush()
    playlist = session.exec(select(Playlist).where(Playlist.user_id == user.id)).first()
    if playlist is None:
        playlist = Playlist(user_id=user.id, spotify_id="pl-1", name="lib")
        session.add(playlist)
        session.flush()
    session.add(
        PlaylistTrack(
            user_id=user.id,
            playlist_id=playlist.id,
            track_id=track.id,
            position=session.exec(select(PlaylistTrack)).all().__len__(),
            added_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    session.commit()
    return track


# --- album art --------------------------------------------------------------


async def test_backfill_album_art_writes_urls(session: Session, user: User) -> None:
    _seed_owned_track(session, user, spotify_id="t-a", album_id="alb1")
    client = FakeImageClient(albums={"alb1": _images()})

    report = await backfill_album_art(session, user, client)

    track = session.exec(select(Track).where(Track.spotify_id == "t-a")).one()
    assert track.image_url == "https://img/large.jpg"
    assert track.image_url_sm == "https://img/small.jpg"
    assert report.tracks_imaged == 1


async def test_backfill_album_art_is_idempotent(session: Session, user: User) -> None:
    _seed_owned_track(session, user, spotify_id="t-a", album_id="alb1")
    client = FakeImageClient(albums={"alb1": _images()})

    await backfill_album_art(session, user, client)
    calls_after_first = len(client.album_batches)

    second = await backfill_album_art(session, user, client)
    # Nothing left to resolve → no further album fetches, no writes.
    assert len(client.album_batches) == calls_after_first
    assert second.tracks_imaged == 0
    assert second.albums_fetched == 0


async def test_backfill_album_art_respects_batch_cap(session: Session, user: User) -> None:
    for i in range(25):
        _seed_owned_track(session, user, spotify_id=f"t-{i}", album_id=f"alb{i}")
    client = FakeImageClient(albums={f"alb{i}": _images() for i in range(25)})

    await backfill_album_art(session, user, client)

    # 25 distinct albums at the 20-cap → two batches, neither over the cap.
    assert [len(b) for b in client.album_batches] == [20, 5]


# --- artist images ----------------------------------------------------------


def _artist_id(i: int) -> str:
    """A valid 22-char base62 Spotify artist id for fixtures."""
    return f"{i:022d}"[:22]


ART1 = "3TVXtAsR1Inumwj472S9r4"  # 22-char base62


async def test_backfill_artist_images_writes_urls(session: Session, user: User) -> None:
    session.add(Artist(spotify_id=ART1, name="BoC"))
    session.commit()
    client = FakeImageClient(artists={ART1: _images()})

    report = await backfill_artist_images(session, client)

    artist = session.exec(select(Artist).where(Artist.spotify_id == ART1)).one()
    assert artist.image_url == "https://img/large.jpg"
    assert artist.image_url_sm == "https://img/small.jpg"
    assert report.artists_imaged == 1


async def test_backfill_artist_images_is_idempotent(session: Session, user: User) -> None:
    session.add(Artist(spotify_id=ART1, name="BoC"))
    session.commit()
    client = FakeImageClient(artists={ART1: _images()})

    await backfill_artist_images(session, client)
    calls_after_first = len(client.artist_batches)

    second = await backfill_artist_images(session, client)
    assert len(client.artist_batches) == calls_after_first
    assert second.artists_imaged == 0
    assert second.artists_fetched == 0


async def test_backfill_artist_images_respects_batch_cap(session: Session, user: User) -> None:
    for i in range(55):
        session.add(Artist(spotify_id=_artist_id(i), name=f"A{i}"))
    session.commit()
    client = FakeImageClient(artists={_artist_id(i): _images() for i in range(55)})

    await backfill_artist_images(session, client)

    assert [len(b) for b in client.artist_batches] == [50, 5]


async def test_backfill_artist_images_skips_non_spotify_ids(session: Session, user: User) -> None:
    """Synthetic artist ids (radio seeds like 'ar-rt-sim') aren't valid Spotify
    base62 ids — including one in a /v1/artists batch 400s the whole call. The
    backfill must never send them."""
    valid = "3TVXtAsR1Inumwj472S9r4"  # 22-char base62
    session.add(Artist(spotify_id=valid, name="Real"))
    session.add(Artist(spotify_id="ar-rt-sim", name="Synthetic"))
    session.commit()
    client = FakeImageClient(artists={valid: _images()})

    report = await backfill_artist_images(session, client)

    # Only the valid id was ever sent to Spotify.
    assert client.artist_batches == [[valid]]
    assert report.artists_imaged == 1
