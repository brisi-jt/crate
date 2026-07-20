"""artist mbid provenance + genre-check marker

Revision ID: d7e1f4a8c592
Revises: c6f0a3b9d2e1
Create Date: 2026-07-20

Hand-written (no autogenerate). Adds two nullable columns to ``artists``:

- ``mbid_source`` records how an artist's MBID was resolved: "isrc" (a track
  ISRC matched a MusicBrainz recording credited to this artist) or "name_search"
  (the conservative name-search fallback for artists whose tracks carry no
  MB-matchable ISRC). Null when the artist has no MBID.
- ``genres_checked_at`` marks when the genre-write pass last fetched MusicBrainz
  genres for the artist's MBID, so an artist MB has no genres for is not
  re-queried every pass. Null = never fetched.

Both are additive and null on existing rows; nothing reads them for correctness,
so a null on a pre-existing MBID is harmless. Each add is guarded by an existence
check, so a partially-applied database re-runs the migration safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e1f4a8c592"
down_revision: str | None = "c6f0a3b9d2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def upgrade() -> None:
    if not _has_column("artists", "mbid_source"):
        op.add_column(
            "artists",
            sa.Column("mbid_source", sa.String(length=16), nullable=True),
        )
    if not _has_column("artists", "genres_checked_at"):
        op.add_column(
            "artists",
            sa.Column("genres_checked_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("artists", "genres_checked_at"):
        op.drop_column("artists", "genres_checked_at")
    if _has_column("artists", "mbid_source"):
        op.drop_column("artists", "mbid_source")
