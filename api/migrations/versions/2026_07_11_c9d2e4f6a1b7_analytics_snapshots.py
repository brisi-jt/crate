"""analytics snapshots

Revision ID: c9d2e4f6a1b7
Revises: a41f7c2d5b83
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

revision: str = "c9d2e4f6a1b7"
down_revision: str | None = "a41f7c2d5b83"
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
    if not _has_table("analytics_snapshots"):
        op.create_table(
            "analytics_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("computed_at", _dt(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "user_id", "kind", "playlist_id", name="uq_analytics_snapshots_scope"
            ),
        )
        op.create_index(
            "ix_analytics_snapshots_user_id", "analytics_snapshots", ["user_id"]
        )


def downgrade() -> None:
    if _has_table("analytics_snapshots"):
        op.drop_table("analytics_snapshots")
