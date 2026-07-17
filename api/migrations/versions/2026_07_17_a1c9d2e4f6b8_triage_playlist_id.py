"""triage playlist setting

Revision ID: a1c9d2e4f6b8
Revises: f4b8c1e63a29
Create Date: 2026-07-17

Hand-written (no autogenerate). Adds a nullable ``users.triage_playlist_id`` —
the per-account triage source. Null means the source is Liked Songs; a set id
names an owned playlist to triage from. No server-side FK (Vitess has none, and
the playlist can be soft-deleted while the id persists), so liveness is
validated in app code at read/apply time. Additive and guarded by an existence
check, so a partially-applied database can re-run it safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c9d2e4f6b8"
down_revision: str | None = "f4b8c1e63a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    if not _has_column("users", "triage_playlist_id"):
        op.add_column("users", sa.Column("triage_playlist_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column("users", "triage_playlist_id"):
        op.drop_column("users", "triage_playlist_id")
