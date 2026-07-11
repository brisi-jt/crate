"""local audio analysis: raw-value sidecar, preview marker, quantile calibration

Revision ID: b3e8f1c6d9a2
Revises: a9d4c7e2f8b1
Create Date: 2026-07-12

Hand-written (no autogenerate). Creates and column adds are guarded by
existence checks so a partially-applied database can re-run the migration
safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b3e8f1c6d9a2"
down_revision: str | None = "a9d4c7e2f8b1"
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
    if not _has_column("track_features", "local_raw"):
        op.add_column("track_features", sa.Column("local_raw", sa.JSON(), nullable=True))
    if not _has_column("track_features", "preview_resolved"):
        op.add_column("track_features", sa.Column("preview_resolved", sa.Boolean(), nullable=True))

    if not _has_table("local_dsp_calibrations"):
        op.create_table(
            "local_dsp_calibrations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("feature", sa.String(32), nullable=False),
            sa.Column("local_anchors", sa.JSON(), nullable=False),
            sa.Column("target_anchors", sa.JSON(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("computed_at", _dt(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("feature", name="uq_local_dsp_calibrations_feature"),
        )


def downgrade() -> None:
    if _has_table("local_dsp_calibrations"):
        op.drop_table("local_dsp_calibrations")
    if _has_column("track_features", "preview_resolved"):
        op.drop_column("track_features", "preview_resolved")
    if _has_column("track_features", "local_raw"):
        op.drop_column("track_features", "local_raw")
