"""POST /v1/previews/refresh endpoint — offline via an injected fake refresher."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_preview_refresher
from crate.model.orm import User
from crate.services.previews.refresh import (
    PreviewTargetNotFound,
    PreviewUnresolvable,
    RefreshedPreview,
)

pytestmark = pytest.mark.unit


def make_client(session: Session, user: User, refresher) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_preview_refresher] = lambda: refresher
    return TestClient(app)


def test_refresh_returns_fresh_url_and_hint(session: Session, user: User) -> None:
    async def refresher(_s, _u, **kwargs):
        assert kwargs == {"track_id": None, "candidate_id": 7, "radio_item_id": None}
        return RefreshedPreview("candidate", 7, "https://fresh/x.mp3")

    client = make_client(session, user, refresher)
    response = client.post("/v1/previews/refresh", json={"candidate_id": 7})
    assert response.status_code == 200
    body = response.json()
    assert body["preview_url"] == "https://fresh/x.mp3"
    assert body["expires_hint_seconds"] == 1200
    assert body["_links"]["self"]["href"] == "/v1/previews/refresh"


def test_refresh_requires_exactly_one_target(session: Session, user: User) -> None:
    async def refresher(_s, _u, **_k):  # never called
        raise AssertionError("refresher should not run")

    client = make_client(session, user, refresher)
    none_given = client.post("/v1/previews/refresh", json={})
    two_given = client.post("/v1/previews/refresh", json={"track_id": 1, "radio_item_id": 2})
    for response in (none_given, two_given):
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["error_code"] == "PREVIEW_TARGET_INVALID"


def test_refresh_404_when_unresolvable(session: Session, user: User) -> None:
    async def refresher(_s, _u, **_k):
        raise PreviewUnresolvable("track", 3)

    client = make_client(session, user, refresher)
    response = client.post("/v1/previews/refresh", json={"track_id": 3})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "PREVIEW_UNRESOLVABLE"


def test_refresh_404_when_target_not_found(session: Session, user: User) -> None:
    async def refresher(_s, _u, **_k):
        raise PreviewTargetNotFound("radio_item", 9)

    client = make_client(session, user, refresher)
    response = client.post("/v1/previews/refresh", json={"radio_item_id": 9})
    assert response.status_code == 404
    assert response.json()["error_code"] == "PREVIEW_TARGET_NOT_FOUND"
