"""weekly digests and radio sessions

Revision ID: c4e7d1a8f5b2
Revises: b3e8f1c6d9a2
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

revision: str = "c4e7d1a8f5b2"
down_revision: str | None = "b3e8f1c6d9a2"
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
    if not _has_table("digests"):
        op.create_table(
            "digests",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("week_start", _dt(), nullable=False),
            sa.Column("generated_at", _dt(), nullable=False),
            sa.Column("read_at", _dt(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("user_id", "week_start", name="uq_digests_user_week"),
        )
        op.create_index("ix_digests_user_id", "digests", ["user_id"])

    if not _has_table("digest_items"):
        op.create_table(
            "digest_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("digest_id", sa.Integer(), sa.ForeignKey("digests.id"), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("section", sa.String(32), nullable=False),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=True),
            sa.Column(
                "candidate_id",
                sa.Integer(),
                sa.ForeignKey("discovery_candidates.id"),
                nullable=True,
            ),
            sa.Column("genre", sa.String(256), nullable=True),
            sa.Column("extra", sa.JSON(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("digest_id", "position", name="uq_digest_items_position"),
        )
        op.create_index("ix_digest_items_digest_id", "digest_items", ["digest_id"])

    if not _has_table("radio_sessions"):
        op.create_table(
            "radio_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("seed_kind", sa.String(32), nullable=False),
            sa.Column(
                "seed_playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=True
            ),
            sa.Column("seed_genre", sa.String(256), nullable=True),
            sa.Column("seed_track_ids", sa.JSON(), nullable=True),
            sa.Column("label", sa.String(512), nullable=False),
            sa.Column("discovery_ratio", sa.Float(), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_radio_sessions_user_id", "radio_sessions", ["user_id"])

    if not _has_table("radio_items"):
        op.create_table(
            "radio_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "session_id", sa.Integer(), sa.ForeignKey("radio_sessions.id"), nullable=False
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=True),
            sa.Column(
                "candidate_id",
                sa.Integer(),
                sa.ForeignKey("discovery_candidates.id"),
                nullable=True,
            ),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("artist", sa.String(512), nullable=False),
            sa.Column("spotify_id", sa.String(64), nullable=True),
            sa.Column("preview_url", sa.Text(), nullable=True),
            sa.Column("tempo", sa.Float(), nullable=True),
            sa.Column("camelot", sa.String(4), nullable=True),
            sa.Column("feedback", sa.String(32), nullable=True),
            sa.Column(
                "journal_id", sa.Integer(), sa.ForeignKey("mutation_journal.id"), nullable=True
            ),
            *_timestamps(),
            sa.UniqueConstraint("session_id", "position", name="uq_radio_items_position"),
        )
        op.create_index("ix_radio_items_session_id", "radio_items", ["session_id"])


def downgrade() -> None:
    for table in ("radio_items", "radio_sessions", "digest_items", "digests"):
        if _has_table(table):
            op.drop_table(table)
