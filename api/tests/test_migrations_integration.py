"""Migration integration tests against the compose/CI MySQL instance."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect

from crate.settings import get_settings

pytestmark = pytest.mark.integration

API_DIR = Path(__file__).parents[1]

EXPECTED_TABLES = {
    "users",
    "spotify_credentials",
    "playlists",
    "tracks",
    "artists",
    "playlist_tracks",
    "sync_events",
    "mutation_journal",
    "track_features",
    "artist_similarities",
    "artist_tags",
    "genres",
    "artist_genres",
    "feature_calibrations",
    "freqblog_budget",
    "api_response_cache",
}


def alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


def drop_everything() -> None:
    engine = create_engine(get_settings().database_url)
    metadata = MetaData()
    metadata.reflect(engine)  # includes alembic_version
    metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def empty_database() -> None:
    drop_everything()


def test_upgrade_head_twice_from_empty_is_idempotent(empty_database: None) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # second run must be a clean no-op

    engine = create_engine(get_settings().database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tables >= EXPECTED_TABLES


def test_upgrade_survives_missing_version_row(empty_database: None) -> None:
    """Re-running against an already-built schema (lost alembic_version) must not fail."""
    config = alembic_config()
    command.upgrade(config, "head")

    # Simulate a database whose schema exists but whose version bookkeeping is gone.
    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE alembic_version")
    engine.dispose()

    command.upgrade(config, "head")  # guards make the creates no-ops

    engine = create_engine(get_settings().database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tables >= EXPECTED_TABLES


def test_downgrade_base_removes_all_tables(empty_database: None) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(get_settings().database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert EXPECTED_TABLES.isdisjoint(tables)
