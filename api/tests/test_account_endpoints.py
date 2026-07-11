"""Account-data endpoint tests — sqlite session + dependency overrides, offline."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_account_sync_runner, get_current_user
from crate.model.enums import TopItemKind, TopTimeRange
from crate.model.orm import PlayEvent, SavedTrack, TopItemsSnapshot, Track, User
from crate.services.account.plays import RecentPlaysReport
from crate.services.account.saved import SavedTracksReport
from crate.services.account.top import TopItemsReport
from crate.services.account.wiring import AccountSyncReport

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_track(session: Session, spotify_id: str) -> Track:
    track = Track(
        spotify_id=spotify_id,
        name=f"Track {spotify_id}",
        artists=[{"spotify_id": f"artist-{spotify_id}", "name": f"Artist {spotify_id}"}],
        album_name="Album",
        duration_ms=180_000,
    )
    session.add(track)
    session.flush()
    return track


def seed_saved(
    session: Session,
    user: User,
    spotify_id: str,
    saved_at: datetime,
    *,
    removed: bool = False,
) -> SavedTrack:
    track = seed_track(session, spotify_id)
    row = SavedTrack(
        user_id=user.id,
        track_id=track.id,
        saved_at=saved_at,
        is_removed=removed,
        removed_at=datetime(2026, 7, 10) if removed else None,
    )
    session.add(row)
    session.commit()
    return row


# --- GET /v1/library/saved ------------------------------------------------------


def test_saved_library_newest_first_with_hal_links(
    client: TestClient, session: Session, user: User
) -> None:
    seed_saved(session, user, "t-old", datetime(2026, 6, 1, 12, 0))
    seed_saved(session, user, "t-new", datetime(2026, 7, 1, 12, 0))

    response = client.get("/v1/library/saved")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["track"]["spotify_id"] for item in body["items"]] == ["t-new", "t-old"]
    first = body["items"][0]
    assert first["saved_at"].startswith("2026-07-01")
    assert first["is_removed"] is False
    assert first["track"]["name"] == "Track t-new"
    assert "self" in body["_links"]


def test_saved_library_pagination_links(client: TestClient, session: Session, user: User) -> None:
    for index in range(3):
        seed_saved(session, user, f"t{index}", datetime(2026, 7, 1 + index))

    body = client.get("/v1/library/saved", params={"limit": 1, "offset": 1}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["_links"]["next"]["href"] == "/v1/library/saved?limit=1&offset=2"
    assert body["_links"]["prev"]["href"] == "/v1/library/saved?limit=1&offset=0"


def test_saved_library_excludes_removed_unless_asked(
    client: TestClient, session: Session, user: User
) -> None:
    seed_saved(session, user, "t-kept", datetime(2026, 7, 1))
    seed_saved(session, user, "t-gone", datetime(2026, 6, 1), removed=True)

    assert client.get("/v1/library/saved").json()["total"] == 1
    body = client.get("/v1/library/saved", params={"include_removed": True}).json()
    assert body["total"] == 2
    removed = next(item for item in body["items"] if item["track"]["spotify_id"] == "t-gone")
    assert removed["is_removed"] is True
    assert removed["removed_at"] is not None


# --- GET /v1/listening/recent -----------------------------------------------------


def test_recent_plays_newest_first(client: TestClient, session: Session, user: User) -> None:
    track = seed_track(session, "t1")
    session.add(
        PlayEvent(
            user_id=user.id,
            track_id=track.id,
            played_at=datetime(2026, 7, 12, 9, 0),
            context_type="playlist",
            context_uri="spotify:playlist:pl1",
        )
    )
    session.add(
        PlayEvent(user_id=user.id, track_id=track.id, played_at=datetime(2026, 7, 12, 10, 0))
    )
    session.commit()

    body = client.get("/v1/listening/recent").json()
    assert body["total"] == 2
    assert [item["played_at"][:16] for item in body["items"]] == [
        "2026-07-12T10:00",
        "2026-07-12T09:00",
    ]
    assert body["items"][1]["context_type"] == "playlist"
    assert body["items"][1]["context_uri"] == "spotify:playlist:pl1"
    assert body["items"][0]["track"]["spotify_id"] == "t1"
    assert body["_links"]["self"]["href"].startswith("/v1/listening/recent")


# --- GET /v1/listening/top --------------------------------------------------------


def snapshot(
    user: User, kind: TopItemKind, time_range: TopTimeRange, captured_at: datetime
) -> TopItemsSnapshot:
    return TopItemsSnapshot(
        user_id=user.id,
        kind=kind,
        time_range=time_range,
        captured_at=captured_at,
        items=[{"rank": 1, "spotify_id": f"{kind}-{time_range}", "name": "X"}],
    )


def test_top_returns_latest_snapshot_per_combo(
    client: TestClient, session: Session, user: User
) -> None:
    stale = datetime(2026, 6, 1)
    fresh = datetime(2026, 7, 1)
    for kind in TopItemKind:
        for time_range in TopTimeRange:
            session.add(snapshot(user, kind, time_range, stale))
            session.add(snapshot(user, kind, time_range, fresh))
    session.commit()

    body = client.get("/v1/listening/top").json()
    assert len(body["items"]) == 6
    assert all(item["captured_at"].startswith("2026-07-01") for item in body["items"])
    combos = {(item["kind"], item["time_range"]) for item in body["items"]}
    assert combos == {(k.value, r.value) for k in TopItemKind for r in TopTimeRange}
    assert body["items"][0]["items"][0]["rank"] == 1


def test_top_filters_by_kind_and_range(client: TestClient, session: Session, user: User) -> None:
    session.add(snapshot(user, TopItemKind.artist, TopTimeRange.short, datetime(2026, 7, 1)))
    session.add(snapshot(user, TopItemKind.track, TopTimeRange.long, datetime(2026, 7, 1)))
    session.commit()

    body = client.get("/v1/listening/top", params={"kind": "artist"}).json()
    assert [item["kind"] for item in body["items"]] == ["artist"]
    body = client.get("/v1/listening/top", params={"time_range": "long"}).json()
    assert [item["time_range"] for item in body["items"]] == ["long"]


def test_top_empty_before_first_capture(client: TestClient) -> None:
    body = client.get("/v1/listening/top").json()
    assert body["items"] == []


# --- POST /v1/account/sync --------------------------------------------------------


def test_account_sync_returns_combined_counts(session: Session, user: User) -> None:
    async def fake_runner(session: Session, user: User) -> AccountSyncReport:
        return AccountSyncReport(
            saved=SavedTracksReport(added=3, removed=1, total_saved=120),
            plays=RecentPlaysReport(captured=7, duplicates=43),
            top=TopItemsReport(snapshots=6),
        )

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_account_sync_runner] = lambda: fake_runner
    client = TestClient(app)

    response = client.post("/v1/account/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["saved_added"] == 3
    assert body["saved_removed"] == 1
    assert body["saved_total"] == 120
    assert body["plays_captured"] == 7
    assert body["top_snapshots"] == 6
    assert body["_links"]["status"]["href"] == "/v1/sync/status"
    assert body["_links"]["saved"]["href"] == "/v1/library/saved"


def test_account_sync_without_credential_conflicts(client: TestClient) -> None:
    response = client.post("/v1/account/sync")
    assert response.status_code == 409
    assert response.json()["error_code"] == "SPOTIFY_NOT_CONNECTED"


# --- GET /v1/sync/status stream timestamps ------------------------------------------


def test_sync_status_reports_stream_capture_times(
    client: TestClient, session: Session, user: User
) -> None:
    empty = client.get("/v1/sync/status").json()
    assert empty["saved_tracks_captured_at"] is None
    assert empty["recent_plays_captured_at"] is None
    assert empty["top_items_captured_at"] is None

    seed_saved(session, user, "t1", datetime(2026, 7, 1))
    track = seed_track(session, "t2")
    session.add(
        PlayEvent(user_id=user.id, track_id=track.id, played_at=datetime(2026, 7, 12, 10, 0))
    )
    session.add(snapshot(user, TopItemKind.artist, TopTimeRange.short, datetime(2026, 7, 2)))
    session.commit()

    body = client.get("/v1/sync/status").json()
    assert body["saved_tracks_captured_at"] is not None
    assert body["recent_plays_captured_at"] is not None
    assert body["top_items_captured_at"].startswith("2026-07-02")
