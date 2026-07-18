"""Triage destinations router: list eligible playlists + bulk-replace exclusions.

GET /v1/triage/destinations lists the account's owned live playlists with each
one's triage_excluded flag and a track count. PUT bulk-replaces the exclusion
set (idempotent): the given ids become excluded, every other owned live
playlist becomes eligible. Unknown / non-owned / dead ids -> 422.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.orm import Playlist, PlaylistTrack, Track, User

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _playlist(
    session: Session,
    user: User,
    name: str,
    *,
    owned: bool = True,
    deleted: bool = False,
    excluded: bool = False,
) -> Playlist:
    pl = Playlist(
        user_id=user.id,
        spotify_id=f"sp-{name}",
        name=name,
        is_owned=owned,
        is_deleted=deleted,
        triage_excluded=excluded,
    )
    session.add(pl)
    session.flush()
    return pl


def _track(session: Session, sid: str) -> int:
    row = Track(spotify_id=sid, name=f"Track {sid}", artists=[])
    session.add(row)
    session.flush()
    assert row.id is not None
    return row.id


def _reload(session: Session, playlist_id: int | None) -> Playlist:
    assert playlist_id is not None
    row = session.get(Playlist, playlist_id)
    assert row is not None
    return row


# -- GET -----------------------------------------------------------------------


def test_list_destinations_owned_live_only(
    client: TestClient, session: Session, user: User
) -> None:
    gym = _playlist(session, user, "Gym")
    _playlist(session, user, "Followed", owned=False)  # not owned -> absent
    _playlist(session, user, "Dead", deleted=True)  # dead -> absent
    _playlist(session, user, "Excluded", excluded=True)
    t = _track(session, "t")
    session.add(PlaylistTrack(user_id=user.id, playlist_id=gym.id, track_id=t, position=0))
    session.commit()

    r = client.get("/v1/triage/destinations")
    assert r.status_code == 200
    body = r.json()
    names = {item["name"] for item in body["items"]}
    assert names == {"Gym", "Excluded"}  # only owned + live
    by_name = {item["name"]: item for item in body["items"]}
    assert by_name["Gym"]["triage_excluded"] is False
    assert by_name["Gym"]["track_count"] == 1
    assert by_name["Excluded"]["triage_excluded"] is True
    assert body["_links"]["self"]["href"] == "/v1/triage/destinations"


def test_list_destinations_empty(client: TestClient) -> None:
    r = client.get("/v1/triage/destinations")
    assert r.status_code == 200
    assert r.json()["items"] == []


# -- PUT (bulk replace) --------------------------------------------------------


def test_put_destinations_bulk_replace(client: TestClient, session: Session, user: User) -> None:
    a = _playlist(session, user, "A", excluded=True)  # currently excluded
    b = _playlist(session, user, "B")  # currently eligible
    c = _playlist(session, user, "C")
    session.commit()

    # Replace the exclusion set with {B}. A becomes eligible, B excluded, C eligible.
    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [b.id]})
    assert r.status_code == 200
    body = r.json()
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[a.id]["triage_excluded"] is False
    assert by_id[b.id]["triage_excluded"] is True
    assert by_id[c.id]["triage_excluded"] is False

    session.expire_all()
    assert _reload(session, a.id).triage_excluded is False
    assert _reload(session, b.id).triage_excluded is True


def test_put_destinations_idempotent(client: TestClient, session: Session, user: User) -> None:
    b = _playlist(session, user, "B")
    session.commit()

    first = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [b.id]})
    second = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [b.id]})
    assert first.status_code == second.status_code == 200
    assert first.json()["items"] == second.json()["items"]


def test_put_destinations_empty_clears_all(
    client: TestClient, session: Session, user: User
) -> None:
    a = _playlist(session, user, "A", excluded=True)
    b = _playlist(session, user, "B", excluded=True)
    session.commit()

    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": []})
    assert r.status_code == 200
    session.expire_all()
    assert _reload(session, a.id).triage_excluded is False
    assert _reload(session, b.id).triage_excluded is False


def test_put_destinations_unknown_id_422(client: TestClient, session: Session, user: User) -> None:
    a = _playlist(session, user, "A")
    session.commit()
    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [a.id, 99999]})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == "INVALID_TRIAGE_PLAYLIST"
    # Nothing changed (validate-before-write).
    session.expire_all()
    assert _reload(session, a.id).triage_excluded is False


def test_put_destinations_non_owned_id_422(
    client: TestClient, session: Session, user: User
) -> None:
    followed = _playlist(session, user, "Followed", owned=False)
    session.commit()
    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [followed.id]})
    assert r.status_code == 422
    assert r.json()["error_code"] == "INVALID_TRIAGE_PLAYLIST"


def test_put_destinations_dead_id_422(client: TestClient, session: Session, user: User) -> None:
    dead = _playlist(session, user, "Dead", deleted=True)
    session.commit()
    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [dead.id]})
    assert r.status_code == 422
    assert r.json()["error_code"] == "INVALID_TRIAGE_PLAYLIST"


# -- snapshot invalidation (kind-selective) ------------------------------------


def test_put_destinations_evicts_cluster_not_track_map(
    client: TestClient, session: Session, user: User
) -> None:
    from crate.model.enums import SnapshotKind
    from crate.model.orm import AnalyticsSnapshot
    from crate.model.orm.base import utcnow

    b = _playlist(session, user, "B")
    # Seed both a triage_cluster snapshot (should evict) and a track_map (should
    # survive — it doesn't read the exclusion set).
    session.add(
        AnalyticsSnapshot(
            user_id=user.id,
            kind=SnapshotKind.triage_cluster,
            playlist_id=None,
            owned_only=True,
            payload={"content_hash": "x", "proposals": []},
            computed_at=utcnow(),
        )
    )
    session.add(
        AnalyticsSnapshot(
            user_id=user.id,
            kind=SnapshotKind.track_map,
            playlist_id=None,
            owned_only=True,
            payload={"points": []},
            computed_at=utcnow(),
        )
    )
    session.commit()

    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [b.id]})
    assert r.status_code == 200

    kinds = {
        row.kind
        for row in session.exec(
            select(AnalyticsSnapshot).where(AnalyticsSnapshot.user_id == user.id)
        ).all()
    }
    assert SnapshotKind.triage_cluster not in kinds  # evicted
    assert SnapshotKind.track_map in kinds  # survives


def test_put_destinations_no_change_keeps_snapshots(
    client: TestClient, session: Session, user: User
) -> None:
    from crate.model.enums import SnapshotKind
    from crate.model.orm import AnalyticsSnapshot
    from crate.model.orm.base import utcnow

    _playlist(session, user, "B", excluded=True)
    session.add(
        AnalyticsSnapshot(
            user_id=user.id,
            kind=SnapshotKind.triage_cluster,
            playlist_id=None,
            owned_only=True,
            payload={"content_hash": "x", "proposals": []},
            computed_at=utcnow(),
        )
    )
    session.commit()
    b_id = session.exec(select(Playlist.id).where(Playlist.name == "B")).one()

    # Re-assert the SAME exclusion set -> nothing changes -> snapshot survives.
    r = client.put("/v1/triage/destinations", json={"excluded_playlist_ids": [b_id]})
    assert r.status_code == 200
    kinds = {
        row.kind
        for row in session.exec(
            select(AnalyticsSnapshot).where(AnalyticsSnapshot.user_id == user.id)
        ).all()
    }
    assert SnapshotKind.triage_cluster in kinds
