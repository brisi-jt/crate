import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import crate.db
import crate.model.orm  # registers all tables on SQLModel.metadata
import crate.settings
from crate.model.orm import User
from tests.db_guard import assert_test_database, derive_test_url


@pytest.fixture
def session():
    """In-memory SQLite session with the full schema — keeps unit tests offline."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="session")
def integration_engine():
    """Engine bound to an isolated ``<name>_test`` database — never the live one.

    Derives the test database from the settings URL (crate → crate_test),
    creates it if missing, and repoints ``get_settings`` at it for the whole
    test session so every consumer — including Alembic's env.py and
    ``crate.db.get_engine`` — targets the test database. All integration
    tests must consume this fixture instead of building their own engine.
    """
    live_settings = crate.settings.get_settings()
    test_url = derive_test_url(live_settings.database_url)  # raises if unsafe

    # Server-level connection (no schema selected) just to create the test DB.
    admin_engine = create_engine(test_url._replace(database=None))
    try:
        with admin_engine.connect() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{test_url.database}`")
    except OperationalError as exc:
        raise RuntimeError(
            f"Could not create test database {test_url.database!r}. The MySQL "
            f"user needs CREATE on it — grant with: GRANT ALL PRIVILEGES ON "
            f"`{test_url.database}`.* TO 'crate'@'%' (as root, see "
            "scripts/mysql-init/)."
        ) from exc
    finally:
        admin_engine.dispose()

    # Repoint the entire process at the test database for the session.
    test_settings = live_settings.model_copy(
        update={"database_url": test_url.render_as_string(hide_password=False)}
    )
    original_get_settings = crate.settings.get_settings
    crate.settings.get_settings = lambda: test_settings  # type: ignore[assignment]
    crate.db.get_engine.cache_clear()

    engine = create_engine(test_url)
    assert_test_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        crate.settings.get_settings = original_get_settings  # type: ignore[assignment]
        crate.db.get_engine.cache_clear()


@pytest.fixture
def user(session: Session) -> User:
    row = User(clerk_user_id="test-user", spotify_user_id="spotify-jt")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
