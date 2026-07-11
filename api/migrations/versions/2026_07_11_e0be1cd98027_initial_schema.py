"""initial schema

Revision ID: e0be1cd98027
Revises:
Create Date: 2026-07-11

Hand-written (no autogenerate). Every create is guarded by an existence check
so a partially-applied database can re-run the migration safely.

Column-type conventions:
- datetimes: DATETIME(6) on MySQL so microseconds survive round trips
- enums: VARCHAR(32) — the ORM maps them as non-native enums, so adding a
  member never needs a migration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "e0be1cd98027"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _dt() -> sa.types.TypeEngine:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
    ]


def upgrade() -> None:
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("clerk_user_id", sa.String(64), nullable=True),
            sa.Column("spotify_user_id", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("clerk_user_id", name="uq_users_clerk_user_id"),
            sa.UniqueConstraint("spotify_user_id", name="uq_users_spotify_user_id"),
        )

    if not _has_table("spotify_credentials"):
        op.create_table(
            "spotify_credentials",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
            sa.Column("access_token_expires_at", _dt(), nullable=True),
            sa.Column("scope", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("user_id", name="uq_spotify_credentials_user"),
        )

    if not _has_table("playlists"):
        op.create_table(
            "playlists",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("spotify_id", sa.String(64), nullable=False),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("snapshot_id", sa.String(128), nullable=True),
            sa.Column("is_owned", sa.Boolean(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("last_synced_at", _dt(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("user_id", "spotify_id", name="uq_playlists_user_spotify"),
        )
        op.create_index("ix_playlists_user_id", "playlists", ["user_id"])

    if not _has_table("tracks"):
        op.create_table(
            "tracks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("spotify_id", sa.String(64), nullable=False),
            sa.Column("isrc", sa.String(16), nullable=True),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("artists", sa.JSON(), nullable=False),
            sa.Column("album_spotify_id", sa.String(64), nullable=True),
            sa.Column("album_name", sa.String(512), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("spotify_id", name="uq_tracks_spotify_id"),
        )
        op.create_index("ix_tracks_isrc", "tracks", ["isrc"])

    if not _has_table("artists"):
        op.create_table(
            "artists",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("spotify_id", sa.String(64), nullable=False),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("mbid", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("spotify_id", name="uq_artists_spotify_id"),
        )

    if not _has_table("playlist_tracks"):
        op.create_table(
            "playlist_tracks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=False),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("added_at", _dt(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("playlist_id", "position", name="uq_playlist_tracks_position"),
        )
        op.create_index("ix_playlist_tracks_user_id", "playlist_tracks", ["user_id"])
        op.create_index("ix_playlist_tracks_track_id", "playlist_tracks", ["track_id"])

    if not _has_table("sync_events"):
        op.create_table(
            "sync_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=False),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=True),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("observed_at", _dt(), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=True),
            *_timestamps(),
        )
        op.create_index("ix_sync_events_user_id", "sync_events", ["user_id"])
        op.create_index("ix_sync_events_playlist_id", "sync_events", ["playlist_id"])
        op.create_index("ix_sync_events_observed_at", "sync_events", ["observed_at"])

    if not _has_table("mutation_journal"):
        op.create_table(
            "mutation_journal",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("op_type", sa.String(32), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("inverse_payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_mutation_journal_user_id", "mutation_journal", ["user_id"])


def downgrade() -> None:
    # Reverse dependency order so foreign keys never dangle.
    for table in (
        "mutation_journal",
        "sync_events",
        "playlist_tracks",
        "artists",
        "tracks",
        "playlists",
        "spotify_credentials",
        "users",
    ):
        if _has_table(table):
            op.drop_table(table)
