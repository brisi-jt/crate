"""Safety-rail regression tests for the integration test-database guard.

These exist because of a real incident: integration tests built engines from
the raw settings URL and `metadata.drop_all` wiped the live local database.
The guard must refuse any destructive helper pointed at a database whose name
does not end in `_test` — before a single connection is opened.
"""

import pytest
from sqlalchemy import create_engine

from crate.settings import get_settings
from tests.db_guard import assert_test_database, derive_test_url, drop_all_tables

pytestmark = pytest.mark.unit

# The exact pattern that caused the incident: an engine built straight from
# the settings URL, pointing at the live database.
LIVE_URL = "mysql+pymysql://crate:crate@127.0.0.1:3308/crate"


def test_guard_refuses_engine_built_from_raw_settings_url() -> None:
    engine = create_engine(get_settings().database_url)
    with pytest.raises(RuntimeError, match="_test"):
        assert_test_database(engine)


def test_guard_refuses_live_database_name() -> None:
    engine = create_engine(LIVE_URL)
    with pytest.raises(RuntimeError, match="_test"):
        assert_test_database(engine)


def test_guard_accepts_test_database_name() -> None:
    engine = create_engine("mysql+pymysql://crate:crate@127.0.0.1:3308/crate_test")
    assert_test_database(engine)  # must not raise


def test_drop_all_tables_refuses_live_engine_before_connecting() -> None:
    # No MySQL required: the guard must reject on the URL alone, before any
    # connection is attempted — that ordering is the incident fix.
    engine = create_engine(LIVE_URL)
    with pytest.raises(RuntimeError, match="_test"):
        drop_all_tables(engine)


def test_derive_test_url_rewrites_database_name() -> None:
    test_url = derive_test_url(LIVE_URL)
    assert test_url.database == "crate_test"
    assert test_url.database.endswith("_test")
    # Everything except the database name is preserved.
    assert test_url.host == "127.0.0.1"
    assert test_url.port == 3308
    assert test_url.username == "crate"


def test_derive_test_url_requires_a_database_name() -> None:
    with pytest.raises(RuntimeError, match="database"):
        derive_test_url("mysql+pymysql://crate:crate@127.0.0.1:3308")


def test_derived_name_always_differs_from_source() -> None:
    # Even a source already ending in _test derives a distinct name — the
    # fixture's "differs from settings DB" invariant can never be vacuous.
    test_url = derive_test_url("mysql+pymysql://crate:crate@127.0.0.1:3308/crate_test")
    assert test_url.database == "crate_test_test"
    assert test_url.database != "crate_test"
