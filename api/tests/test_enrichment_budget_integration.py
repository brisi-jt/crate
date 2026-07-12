"""Budget, staging, and single-flight behaviour against migrated MySQL.

Proves the wall-clock budget honours its deadline and persists honest partial
progress on the real schema, and that a second concurrent run for the same
user is refused with 409 through the real app.
"""

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_enrichment_runner
from crate.model.enums import FeatureStatus
from crate.model.orm import Track, TrackFeatures, User
from crate.services.enrichment.models import AudioFeatures
from crate.services.enrichment.orchestrator import EnrichmentReport, EnrichmentService
from tests.db_guard import drop_all_tables
from tests.test_enrichment_orchestrator import FakeClock, FakeMusicBrainz, FakeRecco
from tests.test_migrations_integration import alembic_config

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_session(integration_engine: Engine):
    drop_all_tables(integration_engine)
    command.upgrade(alembic_config(), "head")
    with Session(integration_engine) as session:
        yield session


async def test_budget_persists_partial_progress_on_mysql(migrated_session: Session) -> None:
    session = migrated_session
    for i in range(4):
        session.add(Track(spotify_id=f"m{i}", name=f"Track {i}", isrc=f"IS{i}", artists=[]))
    session.commit()
    clock = FakeClock()

    class SlowRecco(FakeRecco):
        async def get_audio_features_by_isrc(self, isrc: str):
            clock.advance(100.0)  # each fallback burns 100s of the budget
            return await super().get_audio_features_by_isrc(isrc)

    recco = SlowRecco(by_isrc={f"IS{i}": AudioFeatures(energy=0.5, tempo=120.0) for i in range(4)})
    service = EnrichmentService(reccobeats=recco, musicbrainz=FakeMusicBrainz())

    report = await service.run(session, batch_size=50, time_budget_seconds=250.0, clock=clock)

    assert report.budget_exhausted is True
    persisted = session.exec(select(TrackFeatures)).all()
    # Some but not all tracks made it — honest partial progress, committed.
    assert 1 <= len(persisted) < 4
    assert all(row.status == FeatureStatus.present for row in persisted)
    assert report.stage_seconds["isrc_fallback"] >= 100.0


def test_single_flight_returns_409_through_the_app(migrated_session: Session) -> None:
    session = migrated_session
    user = User(clerk_user_id="budget-int-user")
    session.add(user)
    session.commit()
    session.refresh(user)

    from crate.router import enrichment as enrichment_router

    enrichment_router.reset_active_passes()

    async def runner(
        _session: Session, batch_size: int, *, time_budget_seconds: float, stage: str
    ) -> EnrichmentReport:
        return EnrichmentReport()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_enrichment_runner] = lambda: runner

    client = TestClient(app)
    # A clean run succeeds.
    assert client.post("/v1/enrichment/run").status_code == 200

    # With a pass simulated in-flight, the next run is refused.
    assert user.id is not None
    enrichment_router.mark_active(user.id)
    try:
        blocked = client.post("/v1/enrichment/run")
        assert blocked.status_code == 409
        assert blocked.json()["error_code"] == "ENRICHMENT_PASS_ACTIVE"
    finally:
        enrichment_router.reset_active_passes()
