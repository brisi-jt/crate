"""discovery candidates and suggestion feedback

Revision ID: b6c4d9e2f7a3
Revises: f3a8b6d21c94
Create Date: 2026-07-11

Hand-written (no autogenerate). Creates are guarded by existence checks so a
partially-applied database can re-run the migration safely.

Column-type conventions match the earlier schemas: DATETIME(6) datetimes and
VARCHAR(32) enum columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b6c4d9e2f7a3"
down_revision: str | None = "f3a8b6d21c94"
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
    if not _has_table("discovery_candidates"):
        op.create_table(
            "discovery_candidates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("artist", sa.String(512), nullable=False),
            sa.Column("dedup_key", sa.String(255), nullable=False),
            sa.Column("seed_artist", sa.String(512), nullable=True),
            sa.Column("spotify_id", sa.String(64), nullable=True),
            sa.Column("isrc", sa.String(16), nullable=True),
            sa.Column("album_name", sa.String(512), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("preview_url", sa.Text(), nullable=True),
            sa.Column("features", sa.JSON(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "user_id", "playlist_id", "dedup_key", name="uq_discovery_candidates_identity"
            ),
        )
        op.create_index("ix_discovery_candidates_user_id", "discovery_candidates", ["user_id"])
        op.create_index(
            "ix_discovery_candidates_playlist_id", "discovery_candidates", ["playlist_id"]
        )

    if not _has_table("suggestion_feedback"):
        op.create_table(
            "suggestion_feedback",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "candidate_id",
                sa.Integer(),
                sa.ForeignKey("discovery_candidates.id"),
                nullable=False,
            ),
            sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=False),
            sa.Column("artist", sa.String(512), nullable=False),
            sa.Column("action", sa.String(32), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_suggestion_feedback_user_id", "suggestion_feedback", ["user_id"])
        op.create_index(
            "ix_suggestion_feedback_candidate_id", "suggestion_feedback", ["candidate_id"]
        )
        op.create_index(
            "ix_suggestion_feedback_playlist_id", "suggestion_feedback", ["playlist_id"]
        )
        op.create_index("ix_suggestion_feedback_artist", "suggestion_feedback", ["artist"])


def downgrade() -> None:
    if _has_table("suggestion_feedback"):
        op.drop_table("suggestion_feedback")
    if _has_table("discovery_candidates"):
        op.drop_table("discovery_candidates")
