"""history import: play_events provenance + review table

Revision ID: b2d5e8a1c473
Revises: a1c9d2e4f6b8
Create Date: 2026-07-17

Hand-written (no autogenerate). Two additive changes for lifetime GDPR history
import:

1. ``play_events.source`` (VARCHAR(32), default 'recent') + ``ms_played``
   (nullable int) — provenance so listening analytics can separate all-time
   (recent + import) from since-crate (recent only). Existing rows backfill to
   'recent' via the server default.
2. ``history_import_reviews`` — export lines that could not be resolved to a
   catalog track, parked with their raw payload for a later retry. Unique on
   (user_id, content_key) so re-importing the same export never doubles the
   backlog.

Both are guarded by existence checks so a partially-applied database re-runs
safely. Column-type conventions match the earlier schemas: DATETIME(6)
datetimes, VARCHAR(32) enum columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b2d5e8a1c473"
down_revision: str | None = "a1c9d2e4f6b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dt() -> sa.types.TypeEngine:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def _has_index(table: str, index: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table)
    return any(i["name"] == index for i in indexes)


def upgrade() -> None:
    if not _has_column("play_events", "source"):
        op.add_column(
            "play_events",
            sa.Column(
                "source",
                sa.String(32),
                nullable=False,
                server_default="recent",
            ),
        )
    if not _has_index("play_events", "ix_play_events_source"):
        op.create_index("ix_play_events_source", "play_events", ["source"])
    if not _has_column("play_events", "ms_played"):
        op.add_column("play_events", sa.Column("ms_played", sa.Integer(), nullable=True))

    if not _has_table("history_import_reviews"):
        op.create_table(
            "history_import_reviews",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("content_key", sa.String(128), nullable=False),
            sa.Column("played_at", _dt(), nullable=False),
            sa.Column("raw", sa.JSON(), nullable=False),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=True),
            sa.Column("created_at", _dt(), nullable=False),
            sa.Column("updated_at", _dt(), nullable=False),
            sa.UniqueConstraint(
                "user_id", "content_key", name="uq_history_reviews_user_content"
            ),
        )
        op.create_index("ix_history_import_reviews_user_id", "history_import_reviews", ["user_id"])
        op.create_index("ix_history_import_reviews_status", "history_import_reviews", ["status"])
        op.create_index(
            "ix_history_import_reviews_track_id", "history_import_reviews", ["track_id"]
        )


def downgrade() -> None:
    if _has_table("history_import_reviews"):
        op.drop_table("history_import_reviews")
    if _has_index("play_events", "ix_play_events_source"):
        op.drop_index("ix_play_events_source", "play_events")
    if _has_column("play_events", "ms_played"):
        op.drop_column("play_events", "ms_played")
    if _has_column("play_events", "source"):
        op.drop_column("play_events", "source")
