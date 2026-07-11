"""snapshot owned scope

Revision ID: d8f5a2c7e416
Revises: b6c4d9e2f7a3
Create Date: 2026-07-11

Hand-written (no autogenerate). Adds owned_only to analytics_snapshots so
owned-scope and full-library payloads cache side by side, and widens the
uniqueness key to match. Existing cached rows predate the scope split and
carry no record of which scope they cover, so they are dropped — the cache
refills on the next read.

Guarded by existence checks so a partially-applied database can re-run the
migration safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f5a2c7e416"
down_revision: str | None = "b6c4d9e2f7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "analytics_snapshots"
CONSTRAINT = "uq_analytics_snapshots_scope"


def _has_column(column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(TABLE)
    return any(entry["name"] == column for entry in columns)


def upgrade() -> None:
    if not _has_column("owned_only"):
        op.execute(sa.text(f"DELETE FROM {TABLE}"))
        # The table was just emptied, so the NOT NULL column needs no default.
        op.add_column(TABLE, sa.Column("owned_only", sa.Boolean(), nullable=False))
        op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
        op.create_unique_constraint(
            CONSTRAINT, TABLE, ["user_id", "kind", "playlist_id", "owned_only"]
        )


def downgrade() -> None:
    if _has_column("owned_only"):
        op.execute(sa.text(f"DELETE FROM {TABLE}"))
        op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
        op.drop_column(TABLE, "owned_only")
        op.create_unique_constraint(CONSTRAINT, TABLE, ["user_id", "kind", "playlist_id"])
