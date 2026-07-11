"""saved tracks, play events, top-items snapshots

Revision ID: a9d4c7e2f8b1
Revises: d8f5a2c7e416
Create Date: 2026-07-12

Hand-written (no autogenerate). Creates are guarded by existence checks so a
partially-applied database can re-run the migration safely.

Column-type conventions match the earlier schemas: DATETIME(6) datetimes and
VARCHAR(32) enum columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "a9d4c7e2f8b1"
down_revision: str | None = "d8f5a2c7e416"
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
    if not _has_table("saved_tracks"):
        op.create_table(
            "saved_tracks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
            sa.Column("saved_at", _dt(), nullable=True),
            sa.Column("is_removed", sa.Boolean(), nullable=False),
            sa.Column("removed_at", _dt(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("user_id", "track_id", name="uq_saved_tracks_user_track"),
        )
        op.create_index("ix_saved_tracks_user_id", "saved_tracks", ["user_id"])
        op.create_index("ix_saved_tracks_track_id", "saved_tracks", ["track_id"])

    if not _has_table("play_events"):
        op.create_table(
            "play_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
            sa.Column("played_at", _dt(), nullable=False),
            sa.Column("context_type", sa.String(32), nullable=True),
            sa.Column("context_uri", sa.String(128), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("user_id", "played_at", name="uq_play_events_user_played_at"),
        )
        op.create_index("ix_play_events_user_id", "play_events", ["user_id"])
        op.create_index("ix_play_events_track_id", "play_events", ["track_id"])

    if not _has_table("top_items_snapshots"):
        op.create_table(
            "top_items_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("time_range", sa.String(32), nullable=False),
            sa.Column("captured_at", _dt(), nullable=False),
            sa.Column("items", sa.JSON(), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_top_items_snapshots_user_id", "top_items_snapshots", ["user_id"])
        op.create_index(
            "ix_top_items_snapshots_captured_at", "top_items_snapshots", ["captured_at"]
        )


def downgrade() -> None:
    for table in ("top_items_snapshots", "play_events", "saved_tracks"):
        if _has_table(table):
            op.drop_table(table)
