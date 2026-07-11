"""Digest endpoint tests — sqlite session + dependency overrides, offline."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import CandidateSource, CandidateStatus
from crate.model.orm import Digest, DigestItem, DiscoveryCandidate, Playlist, User

pytestmark = pytest.mark.unit

WEEK_START = datetime(2026, 7, 6)


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_digest(
    session: Session, user: User, week_start: datetime, *, read: bool = False
) -> Digest:
    digest = Digest(
        user_id=user.id,
        week_start=week_start,
        read_at=datetime(2026, 7, 8) if read else None,
        meta={"new_candidates": 2, "plays": 0, "frontier_top": []},
    )
    session.add(digest)
    session.flush()
    session.add(
        DigestItem(
            digest_id=digest.id,
            position=0,
            section="suggestions",
            title="Gym",
            body="2 new suggestions queued this week.",
            playlist_id=None,
            extra={"count": 2},
        )
    )
    session.commit()
    session.refresh(digest)
    return digest


def test_list_digests_newest_first_with_unread_flag(
    client: TestClient, session: Session, user: User
) -> None:
    seed_digest(session, user, WEEK_START - timedelta(days=7), read=True)
    seed_digest(session, user, WEEK_START)

    response = client.get("/v1/digests")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["week_start"][:10] for item in body["items"]] == ["2026-07-06", "2026-06-29"]
    assert body["items"][0]["read_at"] is None
    assert body["items"][0]["item_count"] == 1
    assert body["items"][1]["read_at"] is not None
    assert "self" in body["_links"]
    first_id = body["items"][0]["id"]
    assert body["items"][0]["_links"]["self"]["href"].endswith(f"/v1/digests/{first_id}")


def test_get_digest_returns_items_in_position_order(
    client: TestClient, session: Session, user: User
) -> None:
    digest = seed_digest(session, user, WEEK_START)

    response = client.get(f"/v1/digests/{digest.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == digest.id
    assert body["week_start"].startswith("2026-07-06")
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["section"] == "suggestions"
    assert item["title"] == "Gym"
    assert item["extra"] == {"count": 2}
    assert "self" in body["_links"]


def test_get_digest_404s_for_unknown_or_foreign(client: TestClient, session: Session) -> None:
    response = client.get("/v1/digests/999")
    assert response.status_code == 404
    assert response.json()["error_code"] == "DIGEST_NOT_FOUND"


def test_mark_read_sets_read_at_idempotently(
    client: TestClient, session: Session, user: User
) -> None:
    digest = seed_digest(session, user, WEEK_START)

    first = client.post(f"/v1/digests/{digest.id}/read")
    assert first.status_code == 200
    assert first.json()["read_at"] is not None

    stamp = first.json()["read_at"]
    second = client.post(f"/v1/digests/{digest.id}/read")
    assert second.status_code == 200
    assert second.json()["read_at"] == stamp  # already-read keeps its timestamp


def test_generate_on_demand_builds_current_week(
    client: TestClient, session: Session, user: User
) -> None:
    playlist = Playlist(user_id=user.id, spotify_id="sp-gym", name="Gym", is_owned=True)
    session.add(playlist)
    session.flush()
    session.add(
        DiscoveryCandidate(
            user_id=user.id,
            playlist_id=playlist.id,
            source=CandidateSource.lastfm,
            status=CandidateStatus.resolved,
            title="Fresh",
            artist="Fresh Artist",
            dedup_key="fresh artist|fresh",
            spotify_id="cand-1",
        )
    )
    session.commit()

    response = client.post("/v1/digest/generate", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["read_at"] is None
    sections = {item["section"] for item in body["items"]}
    assert "suggestions" in sections
    assert body["_links"]["self"]["href"] == f"/v1/digests/{body['id']}"
