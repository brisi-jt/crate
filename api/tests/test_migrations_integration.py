"""Migration integration tests against the compose/CI MySQL instance.

All destructive setup goes through tests.db_guard, which refuses any engine
not pointed at a ``*_test`` database.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from tests.db_guard import drop_all_tables, guarded_exec

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
    "analytics_snapshots",
    "op_previews",
    "discovery_candidates",
    "suggestion_feedback",
}


def alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


@pytest.fixture
def empty_database(integration_engine: Engine) -> None:
    drop_all_tables(integration_engine)


def test_upgrade_head_twice_from_empty_is_idempotent(
    integration_engine: Engine, empty_database: None
) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # second run must be a clean no-op

    tables = set(inspect(integration_engine).get_table_names())
    assert tables >= EXPECTED_TABLES


def test_upgrade_survives_missing_version_row(
    integration_engine: Engine, empty_database: None
) -> None:
    """Re-running against an already-built schema (lost alembic_version) must not fail."""
    config = alembic_config()
    command.upgrade(config, "head")

    # Simulate a database whose schema exists but whose version bookkeeping is gone.
    guarded_exec(integration_engine, "DROP TABLE alembic_version")

    command.upgrade(config, "head")  # guards make the creates no-ops

    tables = set(inspect(integration_engine).get_table_names())
    assert tables >= EXPECTED_TABLES


def test_downgrade_base_removes_all_tables(
    integration_engine: Engine, empty_database: None
) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    tables = set(inspect(integration_engine).get_table_names())
    assert EXPECTED_TABLES.isdisjoint(tables)
