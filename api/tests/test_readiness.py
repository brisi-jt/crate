"""Readiness checks and the /readyz probe — offline, engine-injected."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import crate.services.readiness as readiness
from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.orm import User
from crate.services.readiness import (
    ReadinessCheck,
    ReadinessReport,
    check_database,
    check_migration_head,
    evaluate_readiness,
)

pytestmark = pytest.mark.unit


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_check_database_ok_on_live_engine() -> None:
    assert check_database(_sqlite_engine()).ok is True


def test_check_database_fails_on_dead_engine() -> None:
    # A URL that cannot connect stands in for a down database.
    dead = create_engine("sqlite:////nonexistent-dir/does/not/exist.db")
    check = check_database(dead)
    assert check.ok is False
    assert check.name == "database"
    assert check.detail is not None


def test_evaluate_readiness_ready_when_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _sqlite_engine()
    monkeypatch.setattr(
        readiness, "check_migration_head", lambda _e, **_k: ReadinessCheck("migration", True)
    )
    report = evaluate_readiness(engine)
    assert report.ready is True
    assert [c.name for c in report.checks] == ["database", "migration"]


def test_evaluate_readiness_skips_migration_when_db_down() -> None:
    dead = create_engine("sqlite:////nonexistent-dir/does/not/exist.db")
    report = evaluate_readiness(dead)
    assert report.ready is False
    # Migration check is not run once the DB is unreachable — it would only
    # restate the same failure.
    assert [c.name for c in report.checks] == ["database"]


def test_evaluate_readiness_not_ready_on_migration_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _sqlite_engine()
    monkeypatch.setattr(
        readiness,
        "check_migration_head",
        lambda _e, **_k: ReadinessCheck("migration", False, detail="applied 'old' != head 'new'"),
    )
    report = evaluate_readiness(engine)
    assert report.ready is False
    assert [c.name for c in report.failing()] == ["migration"]


def test_check_migration_head_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _sqlite_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('deadbeef')"))
    monkeypatch.setattr(readiness, "_expected_head", lambda: "deadbeef")
    assert check_migration_head(engine).ok is True


def test_check_migration_head_flags_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _sqlite_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('stale00')"))
    monkeypatch.setattr(readiness, "_expected_head", lambda: "fresh99")
    check = check_migration_head(engine)
    assert check.ok is False
    assert "stale00" in (check.detail or "")
    assert "fresh99" in (check.detail or "")


# -- /readyz endpoint -------------------------------------------------------


def test_readyz_returns_200_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda: ReadinessReport(
            ready=True,
            checks=[ReadinessCheck("database", True), ReadinessCheck("migration", True)],
        ),
    )
    client = TestClient(create_app())
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "migration": True}


def test_readyz_returns_503_problem_when_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda: ReadinessReport(
            ready=False,
            checks=[ReadinessCheck("database", False, detail="SELECT 1 failed: OperationalError")],
        ),
    )
    client = TestClient(create_app())
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["error_code"] == "NOT_READY"
    assert "database" in body["detail"]
    assert body["checks"] == {"database": False}


# -- db_ok on /v1/sync/status ----------------------------------------------


def test_sync_status_surfaces_db_ok(session: Session, user: User) -> None:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    response = client.get("/v1/sync/status")
    assert response.status_code == 200
    assert response.json()["db_ok"] is True
