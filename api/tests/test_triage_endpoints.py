"""Triage router contracts: setting, queue, intelligence, apply, cleanup.

create_app() + dependency overrides (session/user/writer_factory/cluster
precomputer), FakeSpotify writer. RFC 7807 + HAL asserted.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import (
    get_current_user,
    get_triage_cluster_precomputer,
    get_writer_factory,
)
from crate.model.enums import FeatureStatus
from crate.model.orm import Playlist, PlaylistTrack, SavedTrack, Track, TrackFeatures, User
from tests.mutation_fakes import FakeSpotify

pytestmark = pytest.mark.unit

HI = {"energy": 0.9, "valence": 0.8, "acousticness": 0.1}


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

    # Synchronous cluster precompute so a "pending" read can be re-driven ready.
    async def sync_precompute(user_id: int, source) -> None:
        from crate.services.triage.cluster import precompute_triage_cluster

        u = session.get(User, user_id)
        assert u is not None
        precompute_triage_cluster(session, u, source)

    app.dependency_overrides[get_triage_cluster_precomputer] = lambda: sync_precompute
    return TestClient(app)


def _track(
    session: Session,
    sid: str,
    artist: str = "A",
    feats: dict | None = None,
    image_url_sm: str | None = None,
) -> int:
    row = Track(
        spotify_id=sid,
        name=f"Track {sid}",
        artists=[{"spotify_id": f"a-{sid}", "name": artist}],
        image_url_sm=image_url_sm,
    )
    session.add(row)
    session.flush()
    assert row.id is not None
    if feats:
        session.add(TrackFeatures(track_id=row.id, status=FeatureStatus.present, **feats))
    return row.id


def _playlist(session: Session, user: User, name: str) -> Playlist:
    pl = Playlist(user_id=user.id, spotify_id=f"sp-{name}", name=name, is_owned=True)
    session.add(pl)
    session.flush()
    return pl


# -- setting -------------------------------------------------------------------


def test_get_triage_setting_default_is_liked(client: TestClient) -> None:
    r = client.get("/v1/me/triage")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "liked"
    assert body["playlist_id"] is None
    assert body["_links"]["queue"]["href"] == "/v1/triage/queue"


def test_put_triage_setting_to_playlist(client: TestClient, session: Session, user: User) -> None:
    pl = _playlist(session, user, "Triage")
    session.commit()
    r = client.put("/v1/me/triage", json={"source": "playlist", "playlist_id": pl.id})
    assert r.status_code == 200
    assert r.json()["source"] == "playlist"
    assert r.json()["playlist_id"] == pl.id
    session.refresh(user)
    assert user.triage_playlist_id == pl.id


def test_put_triage_back_to_liked_clears_playlist(
    client: TestClient, session: Session, user: User
) -> None:
    pl = _playlist(session, user, "Triage")
    session.commit()
    client.put("/v1/me/triage", json={"source": "playlist", "playlist_id": pl.id})
    r = client.put("/v1/me/triage", json={"source": "liked"})
    assert r.status_code == 200
    assert r.json()["source"] == "liked"
    session.refresh(user)
    assert user.triage_playlist_id is None


def test_put_triage_unknown_playlist_422(client: TestClient) -> None:
    r = client.put("/v1/me/triage", json={"source": "playlist", "playlist_id": 999})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == "INVALID_TRIAGE_PLAYLIST"


def test_put_triage_playlist_missing_id_422(client: TestClient) -> None:
    r = client.put("/v1/me/triage", json={"source": "playlist"})
    assert r.status_code == 422


# -- queue ---------------------------------------------------------------------


def test_queue_playlist_mode(client: TestClient, session: Session, user: User) -> None:
    pl = _playlist(session, user, "Triage")
    session.flush()
    for i in range(3):
        session.add(
            PlaylistTrack(
                user_id=user.id, playlist_id=pl.id, track_id=_track(session, f"t{i}"), position=i
            )
        )
    user.triage_playlist_id = pl.id
    session.add(user)
    session.commit()

    r = client.get("/v1/triage/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert body["source"] == "playlist"


def test_queue_items_carry_artist_and_album_art(
    client: TestClient, session: Session, user: User
) -> None:
    """The queue item payload carries the artist name and small album thumb."""
    pl = _playlist(session, user, "Triage")
    session.flush()
    tid = _track(session, "locust", artist="Locust", image_url_sm="https://img/locust-sm.jpg")
    session.add(PlaylistTrack(user_id=user.id, playlist_id=pl.id, track_id=tid, position=0))
    user.triage_playlist_id = pl.id
    session.add(user)
    session.commit()

    r = client.get("/v1/triage/queue")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["artist"] == "Locust"
    assert item["album_image_url"] == "https://img/locust-sm.jpg"


def test_queue_liked_mode_slider(client: TestClient, session: Session, user: User) -> None:
    gym = _playlist(session, user, "Gym")
    session.flush()
    orphan = _track(session, "orphan")
    filed = _track(session, "filed")
    session.add_all(
        [
            SavedTrack(user_id=user.id, track_id=orphan),
            SavedTrack(user_id=user.id, track_id=filed),
            PlaylistTrack(user_id=user.id, playlist_id=gym.id, track_id=filed, position=0),
        ]
    )
    session.commit()

    r = client.get("/v1/triage/queue", params={"max_playlists": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1  # only the orphan
    assert body["source"] == "liked"


# -- intelligence --------------------------------------------------------------


def test_intelligence_returns_four_labeled_signals(
    client: TestClient, session: Session, user: User
) -> None:
    gym = _playlist(session, user, "Gym")
    session.flush()
    for i in range(3):
        session.add(
            PlaylistTrack(
                user_id=user.id,
                playlist_id=gym.id,
                track_id=_track(session, f"g{i}", "Repeat", HI),
                position=i,
            )
        )
    filed = _track(session, "cand", "Repeat", HI)
    session.add(SavedTrack(user_id=user.id, track_id=filed))
    session.commit()

    r = client.get(f"/v1/triage/tracks/{filed}/intelligence")
    assert r.status_code == 200
    body = r.json()
    gym_sug = next(s for s in body["suggestions"] if s["playlist_id"] == gym.id)
    kinds = {e["kind"] for e in gym_sug["evidence"]}
    assert kinds == {"sonic_fit", "artist_overlap", "placement_history", "vibe_match"}
    assert "memberships" in body
    assert "new_category" in body


def test_intelligence_membership_carries_excluded_flag(
    client: TestClient, session: Session, user: User
) -> None:
    """An excluded playlist is still shown as a current membership, badged."""
    gym = _playlist(session, user, "Gym")
    gym.triage_excluded = True
    eligible = _playlist(session, user, "Eligible")
    session.flush()
    filed = _track(session, "cand", "Repeat", HI)
    session.add(PlaylistTrack(user_id=user.id, playlist_id=gym.id, track_id=filed, position=0))
    session.add(PlaylistTrack(user_id=user.id, playlist_id=eligible.id, track_id=filed, position=0))
    session.commit()

    r = client.get(f"/v1/triage/tracks/{filed}/intelligence")
    assert r.status_code == 200
    body = r.json()
    mem = body["memberships"]
    # Both memberships are reported (facts); the excluded one is flagged.
    flags = dict(zip(mem["playlist_ids"], mem["excluded"], strict=True))
    assert flags[gym.id] is True
    assert flags[eligible.id] is False
    # …but the excluded playlist is not a suggestion.
    assert gym.id not in {s["playlist_id"] for s in body["suggestions"]}
    assert eligible.id in {s["playlist_id"] for s in body["suggestions"]}


# -- apply + cleanup -----------------------------------------------------------


def test_apply_files_track_and_journals(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    gym = _playlist(session, user, "Gym")
    focus = _playlist(session, user, "Focus")
    session.flush()
    filed = _track(session, "cand", "A", HI)
    session.commit()
    fake.seed("sp-Gym", "Gym", [])
    fake.seed("sp-Focus", "Focus", [])

    r = client.post(
        "/v1/triage/apply",
        json={"track_id": filed, "destination_playlist_ids": [gym.id, focus.id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "applied"
    assert body["_links"]["undo"]["href"] == f"/v1/journal/{body['journal_id']}/undo"
    order = session.exec(select(PlaylistTrack).where(PlaylistTrack.playlist_id == gym.id)).all()
    assert len(order) == 1


def test_cleanup_unsaves_from_liked(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    t = _track(session, "t")
    session.add(SavedTrack(user_id=user.id, track_id=t))
    fake.seed_saved("t")
    session.commit()

    r = client.post("/v1/triage/cleanup", json={"source": "liked", "track_ids": [t]})
    assert r.status_code == 200
    assert fake.saved == set()
    row = session.exec(select(SavedTrack).where(SavedTrack.track_id == t)).one()
    assert row.is_removed is True


def test_cleanup_removes_from_playlist(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    pl = _playlist(session, user, "Triage")
    session.flush()
    t = _track(session, "t")
    session.add(PlaylistTrack(user_id=user.id, playlist_id=pl.id, track_id=t, position=0))
    fake.seed("sp-Triage", "Triage", ["spotify:track:t"])
    session.commit()

    r = client.post(
        "/v1/triage/cleanup",
        json={"source": "playlist", "playlist_id": pl.id, "track_ids": [t]},
    )
    assert r.status_code == 200
    remaining = session.exec(select(PlaylistTrack).where(PlaylistTrack.playlist_id == pl.id)).all()
    assert remaining == []
