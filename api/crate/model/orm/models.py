"""Persisted models.

Tables are created by hand-written Alembic migrations — keep these definitions
in step with migrations/versions/. The integration round-trip suite verifies
model ↔ migrated-schema agreement field by field.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field

from crate.model.enums import (
    CredentialStatus,
    MutationOpType,
    MutationStatus,
    PlaylistSyncStatus,
    SyncEventSource,
    SyncEventType,
)
from crate.model.orm.base import TimestampedModel, enum_column, utcnow


class User(TimestampedModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    clerk_user_id: str | None = Field(default=None, unique=True, max_length=64)
    spotify_user_id: str | None = Field(default=None, unique=True, max_length=64)


class SpotifyCredential(TimestampedModel, table=True):
    """One Spotify connection per user; tokens are Fernet-encrypted at rest."""

    __tablename__ = "spotify_credentials"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True)
    refresh_token_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    access_token_encrypted: str | None = Field(default=None, sa_column=Column(Text))
    access_token_expires_at: datetime | None = Field(default=None)
    scope: str | None = Field(default=None, max_length=512)
    status: CredentialStatus = Field(
        default=CredentialStatus.active,
        sa_column=enum_column(CredentialStatus, nullable=False),
    )


class Playlist(TimestampedModel, table=True):
    __tablename__ = "playlists"
    __table_args__ = (UniqueConstraint("user_id", "spotify_id", name="uq_playlists_user_spotify"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    spotify_id: str = Field(max_length=64)
    name: str = Field(max_length=512)
    description: str | None = Field(default=None, sa_column=Column(Text))
    snapshot_id: str | None = Field(default=None, max_length=128)
    is_owned: bool = Field(default=True)
    # Set when a sync pass no longer sees the playlist on Spotify. The row and
    # its membership stay for event history.
    is_deleted: bool = Field(default=False)
    status: PlaylistSyncStatus = Field(
        default=PlaylistSyncStatus.pending,
        sa_column=enum_column(PlaylistSyncStatus, nullable=False),
    )
    last_synced_at: datetime | None = Field(default=None)


class Track(TimestampedModel, table=True):
    """Global catalog row — shared across users and playlists."""

    __tablename__ = "tracks"

    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str = Field(unique=True, max_length=64)
    isrc: str | None = Field(default=None, index=True, max_length=16)
    name: str = Field(max_length=512)
    # Ordered [{"spotify_id": ..., "name": ...}] as delivered by Spotify.
    artists: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    album_spotify_id: str | None = Field(default=None, max_length=64)
    album_name: str | None = Field(default=None, max_length=512)
    duration_ms: int | None = Field(default=None)


class Artist(TimestampedModel, table=True):
    """Global catalog row; mbid is filled by the enrichment pipeline."""

    __tablename__ = "artists"

    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str = Field(unique=True, max_length=64)
    name: str = Field(max_length=512)
    mbid: str | None = Field(default=None, max_length=64)


class PlaylistTrack(TimestampedModel, table=True):
    """Playlist membership at the current sync; position is 0-based."""

    __tablename__ = "playlist_tracks"
    __table_args__ = (
        UniqueConstraint("playlist_id", "position", name="uq_playlist_tracks_position"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    playlist_id: int = Field(foreign_key="playlists.id", index=True)
    track_id: int = Field(foreign_key="tracks.id", index=True)
    position: int = Field()
    added_at: datetime | None = Field(default=None)


class SyncEvent(TimestampedModel, table=True):
    """Append-only history of observed and self-inflicted playlist changes."""

    __tablename__ = "sync_events"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    playlist_id: int = Field(foreign_key="playlists.id", index=True)
    # Null for playlist-level events (created/renamed/deleted/reordered).
    track_id: int | None = Field(default=None, foreign_key="tracks.id")
    event_type: SyncEventType = Field(sa_column=enum_column(SyncEventType, nullable=False))
    source: SyncEventSource = Field(
        default=SyncEventSource.sync,
        sa_column=enum_column(SyncEventSource, nullable=False),
    )
    observed_at: datetime = Field(default_factory=utcnow, index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class MutationJournal(TimestampedModel, table=True):
    """Undo log: inverse payload restores the state the operation replaced."""

    __tablename__ = "mutation_journal"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    op_type: MutationOpType = Field(sa_column=enum_column(MutationOpType, nullable=False))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    inverse_payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: MutationStatus = Field(
        default=MutationStatus.pending,
        sa_column=enum_column(MutationStatus, nullable=False),
    )
