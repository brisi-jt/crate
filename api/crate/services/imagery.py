"""Imagery backfill: fill album art and artist photos onto existing rows.

Sync now persists album art and playlist covers going forward, but the rows
that predate the imagery columns need a one-off backfill:

- album art comes from GET /v1/albums (20 ids/call) — the album image is the
  same art the track's album object carries, and one album covers many tracks.
- artist photos come from GET /v1/artists (50 ids/call) — track artist refs
  never carry images, so this is the only source.

Both selections only pick rows still missing an image, so a second run resolves
nothing and writes nothing (idempotent), and a re-run resumes where a previous
one stopped. Every fetch goes through the passed client, whose _request already
backs off on Spotify's 429 Retry-After — the backfills never open a raw HTTP
path that would sidestep the rate limiter.
"""

import re
from dataclasses import dataclass
from typing import Any, Protocol

from sqlmodel import Session, col, select

from crate.model.orm import Artist, PlaylistTrack, Track, User
from crate.services.spotify.models import (
    SpotifyArtist,
    SpotifyImage,
    largest_image_url,
    smallest_image_url,
)

_ALBUMS_BATCH = 20
_ARTISTS_BATCH = 50

# A Spotify id is a 22-character base62 string. Synthetic rows (radio seeds
# like "ar-rt-sim") carry non-Spotify ids; sending even one in a /v1/artists
# batch 400s ("Invalid base62 id") and aborts the whole call.
_SPOTIFY_ID = re.compile(r"^[0-9A-Za-z]{22}$")


class AlbumImageSource(Protocol):
    async def get_albums(self, album_ids: list[str]) -> list[dict[str, Any]]: ...


class ArtistImageSource(Protocol):
    async def get_artists(self, artist_ids: list[str]) -> list[SpotifyArtist]: ...


@dataclass
class AlbumArtReport:
    albums_fetched: int = 0
    albums_missing: int = 0
    tracks_imaged: int = 0


@dataclass
class ArtistImageReport:
    artists_fetched: int = 0
    artists_missing: int = 0
    artists_imaged: int = 0


def _unimaged_album_ids(session: Session, user_id: int) -> list[str]:
    """Album ids on the user's library tracks that still lack album art.

    Scoped to the tracks in the user's playlists (join on playlist_tracks) so
    the shared catalog isn't walked for every account, mirroring the
    release-date backfill.
    """
    rows = session.exec(
        select(Track.album_spotify_id)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user_id)
        .where(col(Track.album_spotify_id).is_not(None))
        .where(col(Track.image_url).is_(None))
        .distinct()
    ).all()
    return sorted({album_id for album_id in rows if album_id})


def _apply_album_images(session: Session, album_id: str, images: list[SpotifyImage]) -> int:
    """Write album art onto every track for one album; return rows updated."""
    large = largest_image_url(images)
    small = smallest_image_url(images)
    if large is None:
        return 0
    tracks = session.exec(select(Track).where(Track.album_spotify_id == album_id)).all()
    updated = 0
    for track in tracks:
        track.image_url = large
        track.image_url_sm = small
        session.add(track)
        updated += 1
    return updated


async def backfill_album_art(
    session: Session, user: User, client: AlbumImageSource
) -> AlbumArtReport:
    """Fill tracks.image_url / image_url_sm from their album's art.

    Idempotent: only albums whose tracks still lack an image are fetched, so a
    completed backfill re-runs into a no-op.
    """
    assert user.id is not None
    report = AlbumArtReport()
    album_ids = _unimaged_album_ids(session, user.id)
    for start in range(0, len(album_ids), _ALBUMS_BATCH):
        batch = album_ids[start : start + _ALBUMS_BATCH]
        albums = await client.get_albums(batch)
        by_id = {album["id"]: album for album in albums if album.get("id")}
        for album_id in batch:
            album = by_id.get(album_id)
            if album is None:
                report.albums_missing += 1
                continue
            report.albums_fetched += 1
            images = [SpotifyImage.model_validate(img) for img in album.get("images", [])]
            report.tracks_imaged += _apply_album_images(session, album_id, images)
        session.commit()
    return report


def _unimaged_artist_ids(session: Session) -> list[str]:
    """Catalog artist spotify ids that still lack a photo.

    Filters out synthetic ids that aren't valid Spotify base62 ids — one bad id
    in a /v1/artists batch fails the entire call.
    """
    rows = session.exec(select(Artist.spotify_id).where(col(Artist.image_url).is_(None))).all()
    return sorted(sid for sid in rows if _SPOTIFY_ID.match(sid))


async def backfill_artist_images(session: Session, client: ArtistImageSource) -> ArtistImageReport:
    """Fill artists.image_url / image_url_sm from GET /v1/artists.

    Idempotent: only artists still lacking a photo are fetched. An artist whose
    Spotify object has no images stays null (nothing to write) and is
    reselected on the next run — a re-run of a fully-imaged catalog is a no-op.
    """
    report = ArtistImageReport()
    artist_ids = _unimaged_artist_ids(session)
    by_spotify_id = {
        row.spotify_id: row
        for row in session.exec(select(Artist).where(col(Artist.spotify_id).in_(artist_ids))).all()
    }
    for start in range(0, len(artist_ids), _ARTISTS_BATCH):
        batch = artist_ids[start : start + _ARTISTS_BATCH]
        fetched = await client.get_artists(batch)
        by_id = {artist.id: artist for artist in fetched}
        for artist_id in batch:
            remote = by_id.get(artist_id)
            if remote is None:
                report.artists_missing += 1
                continue
            report.artists_fetched += 1
            large = largest_image_url(remote.images)
            if large is None:
                continue
            row = by_spotify_id[artist_id]
            row.image_url = large
            row.image_url_sm = smallest_image_url(remote.images)
            session.add(row)
            report.artists_imaged += 1
        session.commit()
    return report
