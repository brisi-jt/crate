"""Production wiring: a SpotifyWriter for the requesting user.

Mirrors run_sync_for_user's credential handling: 409 when no usable
credential exists, needs_reauth flip when Spotify rejects the refresh token,
re-encrypted persistence of rotated tokens.

With CRATE_FAKE_SPOTIFY set (local development only), writes go to a
database-backed stand-in instead of Spotify — every call succeeds, listings
come from local membership, ids and snapshots are invented.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import CredentialStatus
from crate.model.orm import Playlist, PlaylistTrack, SpotifyCredential, Track, User
from crate.services.crypto import get_cipher
from crate.services.mutations.writer import ClientWriter, SpotifyWriter
from crate.services.spotify.client import SpotifyClient, SpotifyReauthRequired
from crate.settings import get_settings


class LocalEchoWriter:
    """SpotifyWriter stand-in for CRATE_FAKE_SPOTIFY demo mode."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _snapshot(self) -> str:
        return f"fake-snap-{uuid.uuid4().hex[:12]}"

    async def list_track_uris(self, playlist_spotify_id: str) -> list[str]:
        playlist = self._session.exec(
            select(Playlist).where(Playlist.spotify_id == playlist_spotify_id)
        ).first()
        if playlist is None:
            return []
        rows = self._session.exec(
            select(Track.spotify_id)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
            .where(PlaylistTrack.playlist_id == playlist.id)
            .order_by(PlaylistTrack.position)
        ).all()
        return [f"spotify:track:{sid}" for sid in rows]

    async def add_tracks(
        self, playlist_spotify_id: str, uris: list[str], position: int | None = None
    ) -> str:
        return self._snapshot()

    async def remove_tracks(self, playlist_spotify_id: str, uris: list[str]) -> str:
        return self._snapshot()

    async def reorder_range(
        self,
        playlist_spotify_id: str,
        range_start: int,
        insert_before: int,
        range_length: int = 1,
    ) -> str:
        return self._snapshot()

    async def create_playlist(self, name: str, description: str | None = None) -> tuple[str, str]:
        return f"fake-pl-{uuid.uuid4().hex[:12]}", self._snapshot()

    async def change_details(
        self,
        playlist_spotify_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        return None

    async def unfollow_playlist(self, playlist_spotify_id: str) -> None:
        return None


def _reauth_conflict() -> AppError:
    return AppError(
        409,
        "Spotify authorization expired",
        detail="Reconnect via /v1/auth/spotify/connect before writing to playlists.",
        error_code="SPOTIFY_REAUTH_REQUIRED",
    )


@asynccontextmanager
async def spotify_client_for_user(session: Session, user: User) -> AsyncIterator[SpotifyClient]:
    """An authenticated SpotifyClient for the user's stored credential.

    Raises 409 when no usable credential exists, flips the credential to
    needs_reauth when Spotify rejects the refresh token, and persists rotated
    tokens (re-encrypted) on the way out. Writes and discovery resolution
    both build on this.
    """
    settings = get_settings()
    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).first()
    if credential is None:
        raise AppError(
            409,
            "Spotify not connected",
            detail="Connect a Spotify account via /v1/auth/spotify/connect before "
            "writing to playlists.",
            error_code="SPOTIFY_NOT_CONNECTED",
        )
    if credential.status == CredentialStatus.needs_reauth:
        raise _reauth_conflict()

    cipher = get_cipher()

    def persist_refresh_token(refresh_token: str) -> None:
        credential.refresh_token_encrypted = cipher.encrypt(refresh_token)

    client = SpotifyClient(
        client_id=settings.spotify_client_id,
        refresh_token=cipher.decrypt(credential.refresh_token_encrypted),
        access_token=(
            cipher.decrypt(credential.access_token_encrypted)
            if credential.access_token_encrypted
            else None
        ),
        on_tokens=persist_refresh_token,
    )
    try:
        yield client
    except SpotifyReauthRequired:
        credential.status = CredentialStatus.needs_reauth
        session.add(credential)
        session.commit()
        raise _reauth_conflict() from None
    finally:
        if client.access_token is not None:
            credential.access_token_encrypted = cipher.encrypt(client.access_token)
            if client.access_token_expires_at is not None:
                credential.access_token_expires_at = client.access_token_expires_at
            session.add(credential)
            session.commit()
        await client.aclose()


@asynccontextmanager
async def spotify_writer_for_user(session: Session, user: User) -> AsyncIterator[SpotifyWriter]:
    settings = get_settings()
    if settings.fake_spotify:
        yield LocalEchoWriter(session)
        return
    async with spotify_client_for_user(session, user) as client:
        yield ClientWriter(client)
