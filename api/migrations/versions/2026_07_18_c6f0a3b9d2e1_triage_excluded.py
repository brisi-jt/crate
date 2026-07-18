"""triage-excluded playlist flag

Revision ID: c6f0a3b9d2e1
Revises: b2d5e8a1c473
Create Date: 2026-07-18

Hand-written (no autogenerate). Adds a non-null ``playlists.triage_excluded``
(default false = eligible), so existing rows and new syncs keep today's
behaviour until the account scopes destinations. A set flag holds a playlist
out of triage: out of suggestion scoring, out of the liked-mode ≤N membership
count, and out of the new-category population. No server-side FK involved.
Additive and guarded by an existence check, so a partially-applied database can
re-run it safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6f0a3b9d2e1"
down_revision: str | None = "b2d5e8a1c473"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    if not _has_column("playlists", "triage_excluded"):
        op.add_column(
            "playlists",
            sa.Column(
                "triage_excluded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _has_column("playlists", "triage_excluded"):
        op.drop_column("playlists", "triage_excluded")
