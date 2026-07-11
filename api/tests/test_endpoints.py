"""API endpoint tests — sqlite session + dependency overrides, fully offline."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_sync_runner
from crate.model.enums import CredentialStatus, PlaylistSyncStatus
from crate.model.orm import Playlist, PlaylistTrack, SpotifyCredential, Track, User, utcnow
from crate.services.sync import SyncReport

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_playlist(session: Session, user: User, name: str, track_ids: list[str]) -> Playlist:
    playlist = Playlist(
        user_id=user.id,
        spotify_id=f"sp-{name}",
        name=name,
        snapshot_id="snap-1",
        status=PlaylistSyncStatus.synced,
        last_synced_at=utcnow(),
    )
    session.add(playlist)
    session.flush()
    for position, tid in enumerate(track_ids):
        track = Track(
            spotify_id=tid,
            name=f"Track {tid}",
            isrc=f"ISRC{tid.upper()}",
            artists=[{"spotify_id": f"artist-{tid}", "name": f"Artist {tid}"}],
            album_name="Album",
            duration_ms=180_000,
        )
        session.add(track)
        session.flush()
        session.add(
            PlaylistTrack(
                user_id=user.id,
                playlist_id=playlist.id,
                track_id=track.id,
                position=position,
                added_at=utcnow(),
            )
        )
    session.commit()
    session.refresh(playlist)
    return playlist


# --- playlists ---------------------------------------------------------------


def test_list_playlists_with_hal_links(client: TestClient, session: Session, user: User) -> None:
    seed_playlist(session, user, "beta", ["t1", "t2"])
    seed_playlist(session, user, "alpha", ["t3"])

    response = client.get("/v1/playlists")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["name"] for item in body["items"]] == ["alpha", "beta"]
    assert body["items"][0]["track_count"] == 1
    assert body["items"][1]["track_count"] == 2
    first = body["items"][0]
    assert first["_links"]["self"]["href"] == f"/v1/playlists/{first['id']}"
    assert first["_links"]["tracks"]["href"] == f"/v1/playlists/{first['id']}/tracks"
    assert "self" in body["_links"]


def test_list_playlists_excludes_deleted_by_default(
    client: TestClient, session: Session, user: User
) -> None:
    playlist = seed_playlist(session, user, "gone", [])
    playlist.is_deleted = True
    session.add(playlist)
    session.commit()

    assert client.get("/v1/playlists").json()["total"] == 0
    assert client.get("/v1/playlists", params={"include_deleted": True}).json()["total"] == 1


def test_list_playlists_owned_filter(client: TestClient, session: Session, user: User) -> None:
    seed_playlist(session, user, "mine", ["t1"])
    followed = seed_playlist(session, user, "theirs", ["t2"])
    followed.is_owned = False
    session.add(followed)
    session.commit()

    # The browse list shows everything unless the caller filters.
    assert client.get("/v1/playlists").json()["total"] == 2
    owned = client.get("/v1/playlists", params={"owned": True}).json()
    assert [item["name"] for item in owned["items"]] == ["mine"]
    followed_only = client.get("/v1/playlists", params={"owned": False}).json()
    assert [item["name"] for item in followed_only["items"]] == ["theirs"]


def test_playlist_tracks_pagination_and_links(
    client: TestClient, session: Session, user: User
) -> None:
    playlist = seed_playlist(session, user, "long", ["t1", "t2", "t3", "t4", "t5"])

    response = client.get(f"/v1/playlists/{playlist.id}/tracks", params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert [item["position"] for item in body["items"]] == [2, 3]
    assert body["items"][0]["track"]["spotify_id"] == "t3"
    assert body["items"][0]["track"]["artists"] == [
        {"spotify_id": "artist-t3", "name": "Artist t3"}
    ]
    links = body["_links"]
    assert links["next"]["href"] == f"/v1/playlists/{playlist.id}/tracks?limit=2&offset=4"
    assert links["prev"]["href"] == f"/v1/playlists/{playlist.id}/tracks?limit=2&offset=0"
    assert links["playlist"]["href"] == f"/v1/playlists/{playlist.id}"


def test_playlist_tracks_404_is_problem_detail(client: TestClient) -> None:
    response = client.get("/v1/playlists/999/tracks")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Playlist not found"
    assert body["status"] == 404
    assert body["error_code"] == "PLAYLIST_NOT_FOUND"


# --- sync --------------------------------------------------------------------


def test_sync_status_before_connection(client: TestClient) -> None:
    response = client.get("/v1/sync/status")
    assert response.status_code == 200
    body = response.json()
    assert body["spotify_connected"] is False
    assert body["needs_reauth"] is False
    assert body["playlist_count"] == 0
    assert body["last_synced_at"] is None
    assert body["_links"]["connect"]["href"] == "/v1/auth/spotify/connect"


def test_sync_status_with_playlists(client: TestClient, session: Session, user: User) -> None:
    seed_playlist(session, user, "alpha", ["t1"])
    session.add(SpotifyCredential(user_id=user.id, refresh_token_encrypted="ct"))
    session.commit()

    body = client.get("/v1/sync/status").json()
    assert body["spotify_connected"] is True
    assert body["needs_reauth"] is False
    assert body["playlist_count"] == 1
    assert body["last_synced_at"] is not None
    assert "connect" not in body["_links"]


def test_sync_without_credential_conflicts(client: TestClient) -> None:
    response = client.post("/v1/sync")
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "SPOTIFY_NOT_CONNECTED"


def test_sync_with_needs_reauth_credential_conflicts(
    client: TestClient, session: Session, user: User
) -> None:
    session.add(
        SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted="ct",
            status=CredentialStatus.needs_reauth,
        )
    )
    session.commit()

    response = client.post("/v1/sync")
    assert response.status_code == 409
    assert response.json()["error_code"] == "SPOTIFY_REAUTH_REQUIRED"

    status = client.get("/v1/sync/status").json()
    assert status["needs_reauth"] is True
    assert status["_links"]["connect"]["href"] == "/v1/auth/spotify/connect"


def test_sync_returns_report_counts(session: Session, user: User) -> None:
    async def fake_runner(session: Session, user: User) -> SyncReport:
        return SyncReport(playlists_created=2, playlists_skipped=1, tracks_added=5)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_sync_runner] = lambda: fake_runner
    client = TestClient(app)

    response = client.post("/v1/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["playlists_created"] == 2
    assert body["playlists_skipped"] == 1
    assert body["tracks_added"] == 5
    assert body["_links"]["status"]["href"] == "/v1/sync/status"


# --- auth dependency -----------------------------------------------------------


def test_unauthenticated_without_dev_user(session: Session) -> None:
    # No get_current_user override and no CRATE_DEV_USER — the dependency 401s.
    from crate.settings import get_settings

    assert get_settings().dev_user is None  # guard: env leakage would mask the test
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    response = client.get("/v1/playlists")
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_REQUIRED"
