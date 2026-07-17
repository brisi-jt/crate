"""imagery columns

Revision ID: f4b8c1e63a29
Revises: e7a2c4f9b310
Create Date: 2026-07-17

Hand-written (no autogenerate). Adds nullable image-url columns so hover cards
can show album art, artist photos, and playlist covers. Spotify already
delivers these URLs in the objects sync fetches; earlier syncs discarded them,
so a backfill fills the existing rows and the sync mapper persists them going
forward. Two resolutions per image where a small thumb helps list/hover perf:
``image_url`` (~640px) and ``image_url_sm`` (~64px).

Additive and guarded by existence checks, so a partially-applied database can
re-run it safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b8c1e63a29"
down_revision: str | None = "e7a2c4f9b310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table)
    return any(c["name"] == column for c in columns)


def _add(table: str, column: str, type_: sa.types.TypeEngine) -> None:
    if not _has_column(table, column):
        op.add_column(table, sa.Column(column, type_, nullable=True))


def upgrade() -> None:
    # Album art from the track's album object.
    _add("tracks", "image_url", sa.String(length=512))
    _add("tracks", "image_url_sm", sa.String(length=512))
    # Artist photo from the /v1/artists batch (backfill) or top-items sync.
    _add("artists", "image_url", sa.String(length=512))
    _add("artists", "image_url_sm", sa.String(length=512))
    # Spotify playlist cover.
    _add("playlists", "image_url", sa.String(length=512))


def downgrade() -> None:
    for table, column in (
        ("playlists", "image_url"),
        ("artists", "image_url_sm"),
        ("artists", "image_url"),
        ("tracks", "image_url_sm"),
        ("tracks", "image_url"),
    ):
        if _has_column(table, column):
            op.drop_column(table, column)
