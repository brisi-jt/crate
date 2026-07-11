"""Write-endpoint contracts: HAL, RFC 7807, journal exposure, preview/apply."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_writer_factory
from crate.model.orm import Playlist, Track, User
from tests.mutation_fakes import FakeSpotify
from tests.test_mutations_service import local_order, seed_library

pytestmark = pytest.mark.unit


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


@pytest.fixture
def client(session: Session, user: User, fake: FakeSpotify) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user

    @asynccontextmanager
    async def fake_writer(_session: Session, _user: User):
        yield fake

    app.dependency_overrides[get_writer_factory] = lambda: fake_writer
    return TestClient(app)


def tid(session: Session, spotify_id: str) -> int:
    row = session.exec(select(Track).where(Track.spotify_id == spotify_id)).one()
    assert row.id is not None
    return row.id


# -- single ops -----------------------------------------------------------------


def test_add_tracks_endpoint(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    response = client.post(
        f"/v1/playlists/{lib['Gym'].id}/tracks",
        json={"track_ids": [tid(session, "t2")]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "applied"
    assert body["track_count"] == 2
    assert body["_links"]["journal"]["href"] == f"/v1/journal/{body['journal_id']}"
    assert body["_links"]["undo"]["href"] == f"/v1/journal/{body['journal_id']}/undo"
    assert local_order(session, lib["Gym"].id) == ["t1", "t2"]


def test_add_tracks_unknown_track_404s(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"]})
    response = client.post(f"/v1/playlists/{lib['Gym'].id}/tracks", json={"track_ids": [999]})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "TRACK_NOT_FOUND"


def test_remove_tracks_endpoint(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3"]})
    response = client.request(
        "DELETE",
        f"/v1/playlists/{lib['Gym'].id}/tracks",
        json={"positions": [1]},
    )
    assert response.status_code == 200
    assert response.json()["track_count"] == 2
    assert local_order(session, lib["Gym"].id) == ["t1", "t3"]


def test_create_playlist_endpoint(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    seed_library(session, user, fake, {"Gym": ["t1"]})
    response = client.post("/v1/playlists", json={"name": "Peak Hours", "description": "night"})
    assert response.status_code == 201
    body = response.json()
    assert body["playlist"]["name"] == "Peak Hours"
    row = session.get(Playlist, body["playlist"]["id"])
    assert row is not None and row.spotify_id


def test_patch_playlist_endpoint(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"]})
    response = client.patch(f"/v1/playlists/{lib['Gym'].id}", json={"name": "Iron Temple"})
    assert response.status_code == 200
    session.refresh(lib["Gym"])
    assert lib["Gym"].name == "Iron Temple"


def test_reorder_endpoint_accepts_flow_payload(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3"]})
    order = [tid(session, s) for s in ["t3", "t1", "t2"]]
    response = client.put(f"/v1/playlists/{lib['Gym'].id}/order", json={"order": order})
    assert response.status_code == 200
    assert local_order(session, lib["Gym"].id) == ["t3", "t1", "t2"]


def test_reorder_endpoint_stale_order_409(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    order = [tid(session, s) for s in ["t1", "t3"]]
    response = client.put(f"/v1/playlists/{lib['Gym'].id}/order", json={"order": order})
    assert response.status_code == 409
    assert response.json()["error_code"] == "ORDER_STALE"


# -- ops preview/apply -------------------------------------------------------------


def test_preview_then_apply_dedupe(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Chill": ["t1", "t2", "t1"]})
    preview_response = client.post(
        "/v1/ops/preview",
        json={"operation": "dedupe", "source_ids": [lib["Chill"].id]},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["manifest"]["summary"]["removes"] == 1
    assert preview["_links"]["apply"]["href"] == "/v1/ops/apply"

    apply_response = client.post("/v1/ops/apply", json={"preview_id": preview["preview_id"]})
    assert apply_response.status_code == 200
    body = apply_response.json()
    assert body["status"] == "applied"
    assert [r["status"] for r in body["results"]] == ["applied"]
    assert local_order(session, lib["Chill"].id) == ["t1", "t2"]


def test_apply_stale_preview_409(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Chill": ["t1", "t2", "t1"], "Pool": ["t3"]})
    preview = client.post(
        "/v1/ops/preview",
        json={"operation": "dedupe", "source_ids": [lib["Chill"].id]},
    ).json()

    # Library moves between preview and apply.
    client.post(
        f"/v1/playlists/{lib['Chill'].id}/tracks",
        json={"track_ids": [tid(session, "t3")]},
    )

    response = client.post("/v1/ops/apply", json={"preview_id": preview["preview_id"]})
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "PREVIEW_STALE"


def test_preview_unknown_playlist_404(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    response = client.post("/v1/ops/preview", json={"operation": "dedupe", "source_ids": [999]})
    assert response.status_code == 404


def test_preview_validation_new_playlist_requires_name(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"A": ["t1"], "B": ["t2"]})
    response = client.post(
        "/v1/ops/preview",
        json={"operation": "union", "source_ids": [lib["A"].id, lib["B"].id]},
    )
    assert response.status_code == 422


# -- journal ----------------------------------------------------------------------


def test_journal_list_and_undo(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    client.post(f"/v1/playlists/{lib['Gym'].id}/tracks", json={"track_ids": [tid(session, "t2")]})

    listing = client.get("/v1/journal")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["op_type"] == "add_tracks"
    assert entry["status"] == "applied"
    assert "Gym" in entry["summary"]
    assert entry["_links"]["undo"]["href"] == f"/v1/journal/{entry['id']}/undo"

    undo = client.post(f"/v1/journal/{entry['id']}/undo")
    assert undo.status_code == 200
    assert undo.json()["status"] == "undone"
    assert local_order(session, lib["Gym"].id) == ["t1"]

    # Undone entries stay in the log, newest first, and lose the undo link.
    after = client.get("/v1/journal").json()
    assert after["items"][0]["status"] == "undone"
    assert "undo" not in after["items"][0]["_links"]


def test_undo_twice_409(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    add = client.post(
        f"/v1/playlists/{lib['Gym'].id}/tracks", json={"track_ids": [tid(session, "t2")]}
    ).json()
    assert client.post(f"/v1/journal/{add['journal_id']}/undo").status_code == 200
    second = client.post(f"/v1/journal/{add['journal_id']}/undo")
    assert second.status_code == 409
    assert second.json()["error_code"] == "NOT_UNDOABLE"


def test_journal_pagination(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2", "t3", "t4"]})
    for sid in ["t2", "t3", "t4"]:
        client.post(
            f"/v1/playlists/{lib['Gym'].id}/tracks", json={"track_ids": [tid(session, sid)]}
        )
    page = client.get("/v1/journal", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert "next" in page["_links"]
