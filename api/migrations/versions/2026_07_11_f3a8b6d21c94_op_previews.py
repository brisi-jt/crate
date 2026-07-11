"""op previews and journal undo timestamp

Revision ID: f3a8b6d21c94
Revises: c9d2e4f6a1b7
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

revision: str = "f3a8b6d21c94"
down_revision: str | None = "c9d2e4f6a1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def _dt() -> sa.types.TypeEngine:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", _dt(), nullable=False),
        sa.Column("updated_at", _dt(), nullable=False),
    ]


def upgrade() -> None:
    if not _has_table("op_previews"):
        op.create_table(
            "op_previews",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("operation", sa.String(32), nullable=False),
            sa.Column("params", sa.JSON(), nullable=False),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_op_previews_user_id", "op_previews", ["user_id"])

    if not _has_column("mutation_journal", "undone_at"):
        op.add_column("mutation_journal", sa.Column("undone_at", _dt(), nullable=True))


def downgrade() -> None:
    if _has_table("op_previews"):
        op.drop_table("op_previews")
    if _has_column("mutation_journal", "undone_at"):
        op.drop_column("mutation_journal", "undone_at")
