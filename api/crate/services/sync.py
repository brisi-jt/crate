"""Playlist sync engine.

Full sync on first observation of a playlist, snapshot_id-gated diff sync
afterwards. Every observed change lands as a SyncEvent row — the event
history the analytics layer replays.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import (
    CredentialStatus,
    PlaylistSyncStatus,
    SyncEventSource,
    SyncEventType,
)
from crate.model.orm import (
    Artist,
    Playlist,
    PlaylistTrack,
    SpotifyCredential,
    SyncEvent,
    Track,
    User,
    utcnow,
)
from crate.services.crypto import get_cipher
from crate.services.spotify.client import SpotifyClient, SpotifyReauthRequired
from crate.services.spotify.models import (
    SpotifyPlaylistSummary,
    SpotifyTrack,
)
from crate.settings import get_settings


class SpotifyReader(Protocol):
    """Read surface of SpotifyClient the sync engine depends on."""

    def iter_playlists(self): ...  # AsyncIterator[SpotifyPlaylistSummary]

    def iter_playlist_tracks(self, playlist_id: str): ...  # AsyncIterator[PlaylistTrackItem]


@dataclass
class SyncReport:
    """Counts from one sync pass."""

    playlists_created: int = 0
    playlists_synced: int = 0
    playlists_renamed: int = 0
    playlists_deleted: int = 0
    playlists_skipped: int = 0
    tracks_added: int = 0
    tracks_removed: int = 0


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class SyncService:
    def __init__(self, *, session: Session, spotify: SpotifyReader, user: User) -> None:
        self._session = session
        self._spotify = spotify
        self._user = user
        self._tracks_by_spotify_id: dict[str, Track] = {}

    async def run(self) -> SyncReport:
        report = SyncReport()
        session = self._session

        remote = [summary async for summary in self._spotify.iter_playlists()]
        local = list(
            session.exec(
                select(Playlist)
                .where(Playlist.user_id == self._user.id)
                .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
            ).all()
        )
        local_by_spotify_id = {p.spotify_id: p for p in local}
        seen: set[str] = set()

        for summary in remote:
            seen.add(summary.id)
            row = local_by_spotify_id.get(summary.id)
            if row is None:
                await self._create_playlist(summary, report)
            else:
                await self._update_playlist(row, summary, report)

        for spotify_id, row in local_by_spotify_id.items():
            if spotify_id not in seen:
                row.is_deleted = True
                session.add(row)
                self._emit(row, SyncEventType.playlist_deleted)
                report.playlists_deleted += 1

        session.commit()
        return report

    async def _create_playlist(self, summary: SpotifyPlaylistSummary, report: SyncReport) -> None:
        session = self._session
        row = Playlist(
            user_id=self._user.id,
            spotify_id=summary.id,
            name=summary.name,
            description=summary.description or None,
            snapshot_id=summary.snapshot_id,
            is_owned=self._is_owned(summary),
            status=PlaylistSyncStatus.synced,
            last_synced_at=utcnow(),
        )
        session.add(row)
        session.flush()
        # First observation is the baseline: membership is recorded but no
        # per-track `added` events are emitted.
        await self._refresh_membership(row, emit_events=False, report=report)
        self._emit(
            row,
            SyncEventType.playlist_created,
            detail={"track_count": summary.tracks.total},
        )
        report.playlists_created += 1

    async def _update_playlist(
        self, row: Playlist, summary: SpotifyPlaylistSummary, report: SyncReport
    ) -> None:
        session = self._session
        if summary.name != row.name:
            self._emit(
                row,
                SyncEventType.playlist_renamed,
                detail={"from": row.name, "to": summary.name},
            )
            row.name = summary.name
            report.playlists_renamed += 1

        if summary.snapshot_id == row.snapshot_id:
            report.playlists_skipped += 1
        else:
            await self._refresh_membership(row, emit_events=True, report=report)
            report.playlists_synced += 1

        row.description = summary.description or None
        row.is_owned = self._is_owned(summary)
        row.snapshot_id = summary.snapshot_id
        row.status = PlaylistSyncStatus.synced
        row.last_synced_at = utcnow()
        session.add(row)

    async def _refresh_membership(
        self, playlist: Playlist, *, emit_events: bool, report: SyncReport
    ) -> None:
        session = self._session
        old_rows = session.exec(
            select(PlaylistTrack, Track)
            .where(PlaylistTrack.playlist_id == playlist.id)
            .where(PlaylistTrack.track_id == Track.id)
            .order_by(PlaylistTrack.position)
        ).all()
        old_order = [track.spotify_id for _, track in old_rows]

        new_entries: list[tuple[Track, datetime | None]] = []
        async for item in self._spotify.iter_playlist_tracks(playlist.spotify_id):
            track = item.track
            if track is None or track.id is None:
                continue  # removed-from-catalog ghosts and local files
            new_entries.append((self._upsert_track(track), _naive_utc(item.added_at)))
        new_order = [track.spotify_id for track, _ in new_entries]

        if emit_events:
            self._emit_membership_events(playlist, old_order, new_order, report)

        for pt_row, _ in old_rows:
            session.delete(pt_row)
        session.flush()  # release (playlist_id, position) before re-inserting
        for position, (track, added_at) in enumerate(new_entries):
            session.add(
                PlaylistTrack(
                    user_id=self._user.id,
                    playlist_id=playlist.id,
                    track_id=track.id,
                    position=position,
                    added_at=added_at,
                )
            )

    def _emit_membership_events(
        self,
        playlist: Playlist,
        old_order: list[str],
        new_order: list[str],
        report: SyncReport,
    ) -> None:
        old_counts = Counter(old_order)
        new_counts = Counter(new_order)

        for spotify_id, count in new_counts.items():
            for _ in range(count - old_counts.get(spotify_id, 0)):
                self._emit(playlist, SyncEventType.added, track_id=self._track_id(spotify_id))
                report.tracks_added += 1

        for spotify_id, count in old_counts.items():
            for _ in range(count - new_counts.get(spotify_id, 0)):
                self._emit(playlist, SyncEventType.removed, track_id=self._track_id(spotify_id))
                report.tracks_removed += 1

        if old_counts == new_counts and old_order != new_order:
            self._emit(playlist, SyncEventType.reordered)

    def _track_id(self, spotify_id: str) -> int | None:
        cached = self._tracks_by_spotify_id.get(spotify_id)
        if cached is not None:
            return cached.id
        row = self._session.exec(select(Track).where(Track.spotify_id == spotify_id)).first()
        if row is not None:
            self._tracks_by_spotify_id[spotify_id] = row
            return row.id
        return None

    def _upsert_track(self, remote: SpotifyTrack) -> Track:
        session = self._session
        assert remote.id is not None  # callers filter local/ghost tracks
        row = self._tracks_by_spotify_id.get(remote.id)
        if row is None:
            row = session.exec(select(Track).where(Track.spotify_id == remote.id)).first()
        artists_json: list[dict[str, Any]] = [
            {"spotify_id": artist.id, "name": artist.name} for artist in remote.artists
        ]
        if row is None:
            row = Track(spotify_id=remote.id, name=remote.name)
            session.add(row)
        row.name = remote.name
        row.isrc = remote.external_ids.isrc
        row.artists = artists_json
        row.album_spotify_id = remote.album.id if remote.album else None
        row.album_name = remote.album.name if remote.album else None
        row.duration_ms = remote.duration_ms
        session.add(row)
        session.flush()
        self._tracks_by_spotify_id[remote.id] = row

        for artist in remote.artists:
            if artist.id is not None:
                self._upsert_artist(artist.id, artist.name)
        return row

    def _upsert_artist(self, spotify_id: str, name: str) -> None:
        session = self._session
        row = session.exec(select(Artist).where(Artist.spotify_id == spotify_id)).first()
        if row is None:
            row = Artist(spotify_id=spotify_id, name=name)
        else:
            row.name = name
        session.add(row)
        session.flush()

    def _is_owned(self, summary: SpotifyPlaylistSummary) -> bool:
        if summary.owner is None or self._user.spotify_user_id is None:
            return False
        return summary.owner.id == self._user.spotify_user_id

    def _emit(
        self,
        playlist: Playlist,
        event_type: SyncEventType,
        *,
        track_id: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            SyncEvent(
                user_id=self._user.id,
                playlist_id=playlist.id,
                track_id=track_id,
                event_type=event_type,
                source=SyncEventSource.sync,
                observed_at=utcnow(),
                detail=detail,
            )
        )


async def run_sync_for_user(session: Session, user: User) -> SyncReport:
    """Production wiring: build a real client from the stored credential and sync.

    Raises AppError (409) when the user has no usable credential; flips the
    credential to needs_reauth when Spotify rejects the refresh token.
    """
    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).first()
    if credential is None:
        raise AppError(
            409,
            "Spotify not connected",
            detail="Connect a Spotify account via /v1/auth/spotify/connect before syncing.",
            error_code="SPOTIFY_NOT_CONNECTED",
        )
    if credential.status == CredentialStatus.needs_reauth:
        raise AppError(
            409,
            "Spotify authorization expired",
            detail="Reconnect via /v1/auth/spotify/connect to resume syncing.",
            error_code="SPOTIFY_REAUTH_REQUIRED",
        )

    cipher = get_cipher()
    settings = get_settings()

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
        report = await SyncService(session=session, spotify=client, user=user).run()
    except SpotifyReauthRequired:
        credential.status = CredentialStatus.needs_reauth
        session.add(credential)
        session.commit()
        raise AppError(
            409,
            "Spotify authorization expired",
            detail="Reconnect via /v1/auth/spotify/connect to resume syncing.",
            error_code="SPOTIFY_REAUTH_REQUIRED",
        ) from None
    finally:
        await client.aclose()

    if client.access_token is not None:
        credential.access_token_encrypted = cipher.encrypt(client.access_token)
        if client.access_token_expires_at is not None:
            credential.access_token_expires_at = client.access_token_expires_at
    session.add(credential)
    session.commit()
    return report
