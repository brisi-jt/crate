"""Extended-insights + pin-candidate endpoint tests over the micro-fixture."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import PlayEventSource
from crate.model.orm import PlayEvent, User
from tests.test_analytics_endpoints import seed_library

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed_plays(session: Session, user: User, ids: dict[str, int]) -> None:
    for i in range(3):
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=ids["t1"],
                played_at=datetime(2024, 6, 3, 9 + i, 0),
                context_type="playlist",
                context_uri="spotify:playlist:sp-Alpha",
                source=PlayEventSource.recent,
            )
        )
    session.commit()


def test_extended_survey_sections(client: TestClient, session: Session, user: User) -> None:
    ids = seed_library(session, user)
    _seed_plays(session, user, ids)
    response = client.get("/v1/insights/extended")
    assert response.status_code == 200
    body = response.json()
    for section in (
        "coverage",
        "play_events",
        "saved",
        "feedback",
        "top_items",
        "radio",
        "journal",
        "cross_table",
    ):
        assert section in body
    assert body["coverage"]["play_events"] == 3
    assert "_links" in body and "insights" in body["_links"]


def test_extended_survey_empty_ok(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    body = client.get("/v1/insights/extended").json()
    assert body["coverage"]["play_events"] == 0
    assert body["play_events"]["listening_clock"]["total"] == 0


def test_pin_candidates_pool_and_tags(client: TestClient, session: Session, user: User) -> None:
    ids = seed_library(session, user)
    _seed_plays(session, user, ids)
    response = client.get("/v1/insights/pins/candidates?surface=insights")
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "insights"
    assert isinstance(body["candidates"], list)
    # every candidate carries the sampler's required metadata.
    for pin in body["candidates"]:
        assert set(pin) >= {"family", "metric_ref", "line", "dismissible_id", "salience"}


def test_pin_candidates_unknown_surface(client: TestClient) -> None:
    response = client.get("/v1/insights/pins/candidates?surface=bogus")
    assert response.status_code == 422
