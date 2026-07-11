"""enrichment schema

Revision ID: a41f7c2d5b83
Revises: e0be1cd98027
Create Date: 2026-07-11

Hand-written (no autogenerate). Every create is guarded by an existence check
so a partially-applied database can re-run the migration safely.

Column-type conventions match the initial schema:
- datetimes: DATETIME(6) on MySQL so microseconds survive round trips
- enums: VARCHAR(32) — the ORM maps them as non-native enums, so adding a
  member never needs a migration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "a41f7c2d5b83"
down_revision: str | None = "e0be1cd98027"
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
    if not _has_table("track_features"):
        op.create_table(
            "track_features",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
            sa.Column("energy", sa.Float(), nullable=True),
            sa.Column("valence", sa.Float(), nullable=True),
            sa.Column("danceability", sa.Float(), nullable=True),
            sa.Column("acousticness", sa.Float(), nullable=True),
            sa.Column("instrumentalness", sa.Float(), nullable=True),
            sa.Column("liveness", sa.Float(), nullable=True),
            sa.Column("speechiness", sa.Float(), nullable=True),
            sa.Column("tempo", sa.Float(), nullable=True),
            sa.Column("key", sa.Integer(), nullable=True),
            sa.Column("mode", sa.Integer(), nullable=True),
            sa.Column("loudness", sa.Float(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("source", sa.String(32), nullable=True),
            sa.Column("fetched_at", _dt(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("track_id", name="uq_track_features_track"),
        )

    if not _has_table("artist_similarities"):
        op.create_table(
            "artist_similarities",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("artist_id", sa.Integer(), sa.ForeignKey("artists.id"), nullable=False),
            sa.Column(
                "similar_artist_id", sa.Integer(), sa.ForeignKey("artists.id"), nullable=True
            ),
            sa.Column("similar_artist_name", sa.String(512), nullable=False),
            sa.Column("similar_artist_mbid", sa.String(64), nullable=True),
            sa.Column("weight", sa.Float(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "artist_id",
                "similar_artist_name",
                "source",
                name="uq_artist_similarities_edge",
            ),
        )
        op.create_index("ix_artist_similarities_artist_id", "artist_similarities", ["artist_id"])

    if not _has_table("artist_tags"):
        op.create_table(
            "artist_tags",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("artist_id", sa.Integer(), sa.ForeignKey("artists.id"), nullable=False),
            sa.Column("tag", sa.String(256), nullable=False),
            sa.Column("weight", sa.Float(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("artist_id", "tag", "source", name="uq_artist_tags_tag"),
        )
        op.create_index("ix_artist_tags_artist_id", "artist_tags", ["artist_id"])

    if not _has_table("genres"):
        op.create_table(
            "genres",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(256), nullable=False),
            sa.Column("enao_rank", sa.Integer(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("name", name="uq_genres_name"),
        )

    if not _has_table("artist_genres"):
        op.create_table(
            "artist_genres",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("genre_id", sa.Integer(), sa.ForeignKey("genres.id"), nullable=False),
            sa.Column("artist_name", sa.String(512), nullable=False),
            sa.Column("artist_id", sa.Integer(), sa.ForeignKey("artists.id"), nullable=True),
            sa.Column("weight", sa.Float(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("genre_id", "artist_name", name="uq_artist_genres_membership"),
        )
        op.create_index("ix_artist_genres_genre_id", "artist_genres", ["genre_id"])
        op.create_index("ix_artist_genres_artist_name", "artist_genres", ["artist_name"])

    if not _has_table("feature_calibrations"):
        op.create_table(
            "feature_calibrations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("feature", sa.String(32), nullable=False),
            sa.Column("p10", sa.Float(), nullable=False),
            sa.Column("p50", sa.Float(), nullable=False),
            sa.Column("p90", sa.Float(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("computed_at", _dt(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("feature", name="uq_feature_calibrations_feature"),
        )

    if not _has_table("freqblog_budget"):
        op.create_table(
            "freqblog_budget",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("month", sa.String(7), nullable=False),
            sa.Column("used", sa.Integer(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("month", name="uq_freqblog_budget_month"),
        )

    if not _has_table("api_response_cache"):
        op.create_table(
            "api_response_cache",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("cache_key", sa.String(255), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("fetched_at", _dt(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("source", "cache_key", name="uq_api_response_cache_key"),
        )


def downgrade() -> None:
    # Reverse dependency order so foreign keys never dangle.
    for table in (
        "api_response_cache",
        "freqblog_budget",
        "feature_calibrations",
        "artist_genres",
        "genres",
        "artist_tags",
        "artist_similarities",
        "track_features",
    ):
        if _has_table(table):
            op.drop_table(table)
