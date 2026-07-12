"""insights: album release dates on tracks, user birth year, insight editions

Revision ID: d5f1a9c3e720
Revises: c4e7d1a8f5b2
Create Date: 2026-07-12

Hand-written (no autogenerate). Column adds and the create are guarded by
existence checks, so a partially-applied database re-runs the migration safely.
Adds:
- tracks.release_date / release_date_precision / release_year (backfilled from
  Spotify /v1/albums via scripts/backfill_release_dates.py)
- users.birth_year (user-supplied, for the taste-freeze coming-of-age band)
- insight_editions (frozen weekly readings — the field journal)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "d5f1a9c3e720"
down_revision: str | None = "c4e7d1a8f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def _has_index(table: str, name: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table)
    return any(i["name"] == name for i in indexes)


def _dt() -> sa.types.TypeEngine:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
    ]


def upgrade() -> None:
    if not _has_column("tracks", "release_date"):
        op.add_column("tracks", sa.Column("release_date", sa.String(10), nullable=True))
    if not _has_column("tracks", "release_date_precision"):
        op.add_column("tracks", sa.Column("release_date_precision", sa.String(5), nullable=True))
    if not _has_column("tracks", "release_year"):
        op.add_column("tracks", sa.Column("release_year", sa.Integer(), nullable=True))
    if not _has_index("tracks", "ix_tracks_release_year"):
        op.create_index("ix_tracks_release_year", "tracks", ["release_year"])

    if not _has_column("users", "birth_year"):
        op.add_column("users", sa.Column("birth_year", sa.Integer(), nullable=True))

    if not _has_table("insight_editions"):
        op.create_table(
            "insight_editions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("week_start", _dt(), nullable=False),
            sa.Column("edition_number", sa.Integer(), nullable=False),
            sa.Column("owned_only", sa.Boolean(), nullable=False),
            sa.Column("generated_at", _dt(), nullable=False),
            sa.Column("headline", sa.JSON(), nullable=False),
            sa.Column("narrative", sa.JSON(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "user_id", "week_start", "owned_only", name="uq_insight_editions_week"
            ),
        )
        op.create_index("ix_insight_editions_user_id", "insight_editions", ["user_id"])


def downgrade() -> None:
    if _has_table("insight_editions"):
        op.drop_table("insight_editions")
    if _has_column("users", "birth_year"):
        op.drop_column("users", "birth_year")
    if _has_index("tracks", "ix_tracks_release_year"):
        op.drop_index("ix_tracks_release_year", "tracks")
    if _has_column("tracks", "release_year"):
        op.drop_column("tracks", "release_year")
    if _has_column("tracks", "release_date_precision"):
        op.drop_column("tracks", "release_date_precision")
    if _has_column("tracks", "release_date"):
        op.drop_column("tracks", "release_date")
