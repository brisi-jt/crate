"""Readiness checks for the /readyz probe.

Liveness (/healthz) answers "is the process up?"; readiness answers "can the
process actually serve traffic right now?" — which for crate means the database
round-trips and the schema is at the migration revision the code expects. The
outage this guards against: /healthz stayed green through three days of a
down database because it never touched one.
"""

from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from crate.db import get_engine

# A readiness probe must never block behind a slow/hung database — a stuck
# probe is as useless as a wrong one. Keep the connect+query budget short.
READINESS_QUERY_TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class ReadinessCheck:
    """Outcome of a single readiness check."""

    name: str
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate readiness across all checks."""

    ready: bool
    checks: list[ReadinessCheck]

    def failing(self) -> list[ReadinessCheck]:
        return [check for check in self.checks if not check.ok]


def check_database(
    engine: Engine, *, timeout: int = READINESS_QUERY_TIMEOUT_SECONDS
) -> ReadinessCheck:
    """Round-trip ``SELECT 1`` within a short timeout."""
    try:
        with engine.connect().execution_options(timeout=timeout) as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return ReadinessCheck(
            name="database", ok=False, detail=f"SELECT 1 failed: {exc.__class__.__name__}"
        )
    return ReadinessCheck(name="database", ok=True)


def _expected_head() -> str | None:
    """The head revision the shipped migrations define (code's expectation)."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = Path(__file__).resolve().parents[2]
    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    # A single linear history has exactly one head; anything else is a
    # branched/misconfigured tree we should not declare "matched" against.
    return heads[0] if len(heads) == 1 else None


def _current_revision(engine: Engine, *, timeout: int) -> str | None:
    with engine.connect().execution_options(timeout=timeout) as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row is not None else None


def check_migration_head(
    engine: Engine, *, timeout: int = READINESS_QUERY_TIMEOUT_SECONDS
) -> ReadinessCheck:
    """Compare the DB's applied revision against the migrations' head.

    Cheap: reads the ``alembic_version`` table rather than running any
    migration. A mismatch means the process is running against a schema it was
    not built for — not ready to serve.
    """
    try:
        expected = _expected_head()
    except Exception as exc:  # a broken migration tree is itself not-ready
        return ReadinessCheck(
            name="migration",
            ok=False,
            detail=f"could not resolve expected head: {exc.__class__.__name__}",
        )
    if expected is None:
        return ReadinessCheck(name="migration", ok=False, detail="migrations have no single head")
    try:
        current = _current_revision(engine, timeout=timeout)
    except SQLAlchemyError as exc:
        return ReadinessCheck(
            name="migration",
            ok=False,
            detail=f"could not read applied revision: {exc.__class__.__name__}",
        )
    if current != expected:
        return ReadinessCheck(
            name="migration",
            ok=False,
            detail=f"applied revision {current!r} does not match expected head {expected!r}",
        )
    return ReadinessCheck(name="migration", ok=True)


def evaluate_readiness(engine: Engine | None = None) -> ReadinessReport:
    """Run every readiness check and aggregate.

    The database check runs first; if the DB is unreachable the migration check
    would only restate the same failure, so it is skipped.
    """
    engine = engine or get_engine()
    db = check_database(engine)
    checks = [db]
    if db.ok:
        checks.append(check_migration_head(engine))
    return ReadinessReport(ready=all(check.ok for check in checks), checks=checks)
