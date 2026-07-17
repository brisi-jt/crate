"""Production wiring: a SpotifyWriter for the requesting user.

Mirrors run_sync_for_user's credential handling: 409 when no usable
credential exists, needs_reauth flip when Spotify rejects the refresh token,
re-encrypted persistence of rotated tokens.

With CRATE_FAKE_SPOTIFY set (local development only), writes go to a
database-backed stand-in instead of Spotify — every call succeeds, listings
come from local membership, ids and snapshots are invented.
"""

import contextlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import CredentialStatus
from crate.model.orm import Playlist, PlaylistTrack, SpotifyCredential, Track, User
from crate.model.orm.base import utcnow
from crate.services.crypto import get_cipher
from crate.services.mutations.writer import ClientWriter, SpotifyWriter
from crate.services.spill import write_spill
from crate.services.spotify.client import SpotifyClient, SpotifyReauthRequired
from crate.services.spotify.problems import reauth_conflict
from crate.services.storage import ping_engine
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

    async def add_saved_tracks(self, track_spotify_ids: list[str]) -> None:
        return None

    async def remove_saved_tracks(self, track_spotify_ids: list[str]) -> None:
        return None


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
    if credential.status.requires_reauth:
        raise reauth_conflict(credential.status)

    cipher = get_cipher()
    engine = session.get_bind()
    # Holds the encrypted just-rotated refresh token so a persist failure can
    # spill exactly that value rather than lose it. None until a rotation lands.
    rotated_encrypted: dict[str, str | None] = {"value": None}

    def persist_refresh_token(refresh_token: str) -> None:
        encrypted = cipher.encrypt(refresh_token)
        credential.refresh_token_encrypted = encrypted
        rotated_encrypted["value"] = encrypted

    client = SpotifyClient(
        client_id=settings.spotify_client_id,
        refresh_token=cipher.decrypt(credential.refresh_token_encrypted),
        access_token=(
            cipher.decrypt(credential.access_token_encrypted)
            if credential.access_token_encrypted
            else None
        ),
        on_tokens=persist_refresh_token,
        preflight=lambda: ping_engine(engine),
        use_items_endpoints=settings.spotify_use_items_endpoints,
    )
    try:
        yield client
    except SpotifyReauthRequired as exc:
        credential.status = CredentialStatus.for_reauth_reason(exc.reason)
        session.add(credential)
        session.commit()
        raise reauth_conflict(credential.status) from None
    finally:
        if client.access_token is not None:
            credential.access_token_encrypted = cipher.encrypt(client.access_token)
            if client.access_token_expires_at is not None:
                credential.access_token_expires_at = client.access_token_expires_at
            session.add(credential)
            try:
                session.commit()
            except Exception:
                # The DB died between the passing preflight and this write. A
                # rotated refresh token is unrecoverable if lost, so spill it;
                # a healthy tick reconciles it back. Access-token-only failures
                # are not spilled — access tokens are re-derivable via refresh.
                if rotated_encrypted["value"] is not None:
                    with contextlib.suppress(Exception):
                        session.rollback()
                    write_spill(
                        credential.user_id,
                        rotated_encrypted["value"],
                        rotated_at=utcnow(),
                    )
                await client.aclose()
                raise
        await client.aclose()


@asynccontextmanager
async def spotify_writer_for_user(session: Session, user: User) -> AsyncIterator[SpotifyWriter]:
    settings = get_settings()
    if settings.fake_spotify:
        yield LocalEchoWriter(session)
        return
    async with spotify_client_for_user(session, user) as client:
        yield ClientWriter(client)
