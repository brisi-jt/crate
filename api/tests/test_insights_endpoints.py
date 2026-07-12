"""Insights, editions, pins, and /v1/me endpoint tests over the micro-fixture."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.orm import Track, User
from tests.test_analytics_endpoints import seed_library

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_insights_survey_sections(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    response = client.get("/v1/insights")
    assert response.status_code == 200
    body = response.json()
    for section in (
        "coverage",
        "taste_identity",
        "sonic_signatures",
        "archaeology",
        "eras",
        "extremes",
    ):
        assert section in body
    assert body["coverage"]["enriched_tracks"] == 5
    assert len(body["taste_identity"]["fingerprint"]) == 9
    assert "_links" in body and "editions" in body["_links"]


def test_insights_camelot_all_present(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    body = client.get("/v1/insights").json()
    camelot = body["sonic_signatures"]["camelot"]
    assert camelot and camelot[0]["code"] == "8B"


def test_compile_and_list_editions(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    compiled = client.post("/v1/insights/editions/compile")
    assert compiled.status_code == 200
    edition = compiled.json()
    assert edition["edition_number"] == 1
    assert any(line["kind"] == "baseline" for line in edition["narrative"])

    listing = client.get("/v1/insights/editions")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    fetched = client.get(f"/v1/insights/editions/{edition['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == edition["id"]


def test_get_missing_edition_404(client: TestClient) -> None:
    response = client.get("/v1/insights/editions/999")
    assert response.status_code == 404
    assert response.json()["error_code"] == "EDITION_NOT_FOUND"


def test_pins_field_surface(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    response = client.get("/v1/insights/pins", params={"surface": "field"})
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "field"
    assert all("dismissible_id" in pin for pin in body["pins"])


def test_pins_unknown_surface_422(client: TestClient) -> None:
    response = client.get("/v1/insights/pins", params={"surface": "nope"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "UNKNOWN_SURFACE"


def test_pins_galaxy_surface(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    response = client.get("/v1/insights/pins", params={"surface": "galaxy"})
    assert response.status_code == 200
    assert response.json()["surface"] == "galaxy"


# ------------------------------------------------------------------- /v1/me


def test_get_me_default_no_birth_year(client: TestClient, user: User) -> None:
    response = client.get("/v1/me")
    assert response.status_code == 200
    assert response.json()["birth_year"] is None


def test_patch_me_sets_birth_year(client: TestClient, session: Session, user: User) -> None:
    response = client.patch("/v1/me", json={"birth_year": 1992})
    assert response.status_code == 200
    assert response.json()["birth_year"] == 1992
    session.refresh(user)
    assert user.birth_year == 1992


def test_patch_me_rejects_future_birth_year(client: TestClient) -> None:
    response = client.patch("/v1/me", json={"birth_year": 2030})
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_BIRTH_YEAR"


def test_patch_me_rejects_too_old(client: TestClient) -> None:
    response = client.patch("/v1/me", json={"birth_year": 1800})
    assert response.status_code == 422


def test_patch_me_clears_birth_year(client: TestClient, session: Session, user: User) -> None:
    user.birth_year = 1990
    session.add(user)
    session.commit()
    response = client.patch("/v1/me", json={"birth_year": None})
    assert response.status_code == 200
    assert response.json()["birth_year"] is None


# --------------------------------------------------- map features (item 1)


def test_map_points_carry_features_and_playlist_ids(session: Session, user: User) -> None:
    """The map projects only when ≥10 tracks are enriched; each point then
    carries the 3-value centroid features and its owning playlist ids."""
    from crate.model.enums import FeatureSource, FeatureStatus, PlaylistSyncStatus
    from crate.model.orm import Playlist, PlaylistTrack, TrackFeatures, utcnow
    from crate.services.analytics import engine

    playlist = Playlist(
        user_id=user.id,
        spotify_id="sp-big",
        name="Big",
        status=PlaylistSyncStatus.synced,
        last_synced_at=utcnow(),
    )
    session.add(playlist)
    session.flush()
    for i in range(1, 13):
        track = Track(spotify_id=f"sp-b{i}", name=f"B{i}", artists=[{"name": f"Art {i}"}])
        session.add(track)
        session.flush()
        session.add(
            TrackFeatures(
                track_id=track.id,
                energy=i / 12,
                valence=(13 - i) / 12,
                danceability=i / 12,
                acousticness=i / 12,
                instrumentalness=i / 12,
                liveness=i / 12,
                speechiness=i / 12,
                tempo=100.0 + i,
                loudness=-10.0 + i,
                key=i % 12,
                mode=i % 2,
                status=FeatureStatus.present,
                source=FeatureSource.reccobeats,
            )
        )
        session.add(
            PlaylistTrack(
                user_id=user.id, playlist_id=playlist.id, track_id=track.id, position=i - 1
            )
        )
    session.commit()

    payload = engine.compute_track_map_payload(session, user, owned_only=True)
    points = payload["points"]
    assert points
    for point in points:
        assert set(point["features"]) == {"acousticness", "energy", "valence"}
        assert point["playlist_ids"] == [playlist.id]
