"""History-import API surface: review listing + listening-range toggle."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import HistoryImportStatus, PlayEventSource
from crate.model.orm import HistoryImportReview, PlayEvent, Track, User

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_track(session: Session, spotify_id: str) -> Track:
    track = Track(spotify_id=spotify_id, name=f"Track {spotify_id}", duration_ms=180_000)
    session.add(track)
    session.flush()
    return track


def seed_play(session: Session, user: User, spotify_id: str, at: datetime, source: PlayEventSource):
    track = seed_track(session, spotify_id)
    session.add(PlayEvent(user_id=user.id, track_id=track.id, played_at=at, source=source))
    session.commit()


def seed_review(session: Session, user: User, key: str, status: HistoryImportStatus):
    session.add(
        HistoryImportReview(
            user_id=user.id,
            status=status,
            content_key=key,
            played_at=datetime(2021, 1, 1),
            raw={"spotify_track_uri": f"spotify:track:{key}"},
        )
    )
    session.commit()


def test_reviews_endpoint_lists_pending_by_default(
    client: TestClient, session: Session, user: User
):
    seed_review(session, user, "a", HistoryImportStatus.pending)
    seed_review(session, user, "b", HistoryImportStatus.skipped)

    resp = client.get("/v1/history/import/reviews")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "pending"
    assert "_links" in body


def test_reviews_endpoint_filters_by_status(client: TestClient, session: Session, user: User):
    seed_review(session, user, "a", HistoryImportStatus.pending)
    seed_review(session, user, "b", HistoryImportStatus.skipped)

    resp = client.get("/v1/history/import/reviews?status=skipped")

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["status"] == "skipped"


def test_listening_range_all_time_includes_imports(
    client: TestClient, session: Session, user: User
):
    seed_play(session, user, "native", datetime(2026, 7, 1), PlayEventSource.recent)
    seed_play(session, user, "old", datetime(2019, 1, 1), PlayEventSource.import_)

    resp = client.get("/v1/listening/recent?range=all_time")

    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_listening_range_since_crate_excludes_imports(
    client: TestClient, session: Session, user: User
):
    seed_play(session, user, "native", datetime(2026, 7, 1), PlayEventSource.recent)
    seed_play(session, user, "old", datetime(2019, 1, 1), PlayEventSource.import_)

    resp = client.get("/v1/listening/recent?range=since_crate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["track"]["spotify_id"] == "native"


def test_listening_default_range_is_all_time(client: TestClient, session: Session, user: User):
    seed_play(session, user, "native", datetime(2026, 7, 1), PlayEventSource.recent)
    seed_play(session, user, "old", datetime(2019, 1, 1), PlayEventSource.import_)

    resp = client.get("/v1/listening/recent")

    assert resp.status_code == 200
    assert resp.json()["total"] == 2
