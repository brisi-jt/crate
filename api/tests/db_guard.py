"""Safety rails for integration tests that touch a real MySQL server.

Integration tests must never run destructive operations against the live
database the API itself uses. Every destructive helper here checks — from the
engine URL alone, before opening any connection — that the target database
name ends in ``_test``.
"""

from sqlalchemy import Engine, MetaData
from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL


def derive_test_url(database_url: str) -> URL:
    """Rewrite a database URL to its isolated ``<name>_test`` sibling."""
    url = make_url(database_url)
    if not url.database:
        raise RuntimeError(
            f"Cannot derive a test database from {url.render_as_string()!r}: "
            "the URL has no database name."
        )
    test_name = f"{url.database}_test"
    if not test_name.endswith("_test") or test_name == url.database:
        raise RuntimeError(
            f"Derived test database {test_name!r} failed its safety invariant "
            f"(must end in '_test' and differ from {url.database!r})."
        )
    return url.set(database=test_name)


def assert_test_database(engine: Engine) -> None:
    """Raise unless the engine points at a ``*_test`` database.

    Checks the URL only — no connection is opened — so a mistargeted engine is
    rejected before it can touch the server at all.
    """
    name = engine.url.database
    if not name or not name.endswith("_test"):
        raise RuntimeError(
            f"Refusing destructive test operation against database {name!r}: "
            "integration tests may only touch databases named '*_test'. "
            "Use the `integration_engine` fixture instead of building an "
            "engine from the settings URL."
        )


def drop_all_tables(engine: Engine) -> None:
    """Drop every table (including alembic_version) — test databases only."""
    assert_test_database(engine)
    metadata = MetaData()
    metadata.reflect(engine)
    metadata.drop_all(engine)


def guarded_exec(engine: Engine, sql: str) -> None:
    """Run raw destructive SQL (e.g. ``DROP TABLE``) — test databases only."""
    assert_test_database(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
