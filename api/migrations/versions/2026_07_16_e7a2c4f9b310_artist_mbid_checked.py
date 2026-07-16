"""artist mbid attempt marker

Revision ID: e7a2c4f9b310
Revises: d5f1a9c3e720
Create Date: 2026-07-16

Hand-written (no autogenerate). Adds a nullable ``artists.mbid_checked_at`` so
the identity stage marks artists it has attempted an MBID for and does not
re-select the un-resolvable long tail every pass. Additive and guarded by an
existence check, so a partially-applied database can re-run it safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "e7a2c4f9b310"
down_revision: str | None = "d5f1a9c3e720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def _dt() -> sa.types.TypeEngine:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    if not _has_column("artists", "mbid_checked_at"):
        op.add_column("artists", sa.Column("mbid_checked_at", _dt(), nullable=True))


def downgrade() -> None:
    if _has_column("artists", "mbid_checked_at"):
        op.drop_column("artists", "mbid_checked_at")
