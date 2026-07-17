"""F-series router contracts: rhythm, obscurity, quality, drift, flow-arc.

create_app() + dependency overrides. F4's arc apply goes through the existing
journaled reorder (MutationService.reorder) against FakeSpotify — the same
write path singles use — and is undoable. Read endpoints (F1/F3/F5/F6) run over
the shared analytics micro-fixture.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_writer_factory
from crate.model.enums import (
    FeatureStatus,
    MutationStatus,
    PlayEventSource,
    TopItemKind,
    TopTimeRange,
)
from crate.model.orm import (
    ArtistGenre,
    Genre,
    MutationJournal,
    PlayEvent,
    TopItemsSnapshot,
    TrackFeatures,
    User,
)
from tests.mutation_fakes import FakeSpotify
from tests.test_analytics_endpoints import seed_library

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


# --------------------------------------------------------------- F1 rhythm


def test_rhythm_dashboard(client: TestClient, session: Session, user: User) -> None:
    ids = seed_library(session, user)
    for hour, minute in ((9, 0), (9, 15), (10, 0)):
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=ids["t1"],
                played_at=datetime(2024, 6, 1, hour, minute),
                source=PlayEventSource.recent,
            )
        )
    session.commit()
    response = client.get("/v1/listening/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["total_plays"] == 3
    assert body["clock"]["peak_hour"] == 9
    assert body["range"] == "all_time"
    assert body["_links"]["self"]["href"] == "/v1/listening/dashboard"


def test_rhythm_range_since_crate(client: TestClient, session: Session, user: User) -> None:
    ids = seed_library(session, user)
    session.add(
        PlayEvent(
            user_id=user.id,
            track_id=ids["t1"],
            played_at=datetime(2020, 1, 1, 9, 0),
            source=PlayEventSource.import_,
        )
    )
    session.add(
        PlayEvent(
            user_id=user.id,
            track_id=ids["t1"],
            played_at=datetime(2024, 6, 1, 9, 0),
            source=PlayEventSource.recent,
        )
    )
    session.commit()
    all_time = client.get("/v1/listening/dashboard?range=all_time").json()
    since = client.get("/v1/listening/dashboard?range=since_crate").json()
    assert all_time["total_plays"] == 2
    assert since["total_plays"] == 1
    assert since["range"] == "since_crate"


# --------------------------------------------------------------- F3 obscurity


def test_obscurity_report(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    pop = Genre(name="pop", enao_rank=1)
    niche = Genre(name="witch house", enao_rank=5000)
    session.add(pop)
    session.add(niche)
    session.flush()
    session.add(ArtistGenre(genre_id=pop.id, artist_name="Artist 1", weight=1.0))
    session.add(ArtistGenre(genre_id=niche.id, artist_name="Artist 6", weight=1.0))
    session.commit()
    response = client.get("/v1/obscurity")
    assert response.status_code == 200
    body = response.json()
    assert body["library"]["score"] is not None
    assert body["source"] == "enao_rank"
    assert body["lastfm_pending"] is True
    assert any(p["name"] == "Alpha" for p in body["playlists"])


# ----------------------------------------------------------------- F6 quality


def test_quality_report(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    response = client.get("/v1/quality/playlists")
    assert response.status_code == 200
    body = response.json()
    alpha = next(p for p in body["playlists"] if p["name"] == "Alpha")
    assert alpha["score"] is not None
    refs = {s["ref"] for s in alpha["subscores"]}
    assert "quality_cohesion" in refs
    assert set(body["subscore_refs"]) >= {
        "quality_cohesion",
        "quality_uniqueness",
        "quality_freshness",
        "quality_flow",
    }


# ------------------------------------------------------------------- F5 drift


def test_drift_timeline_and_comparison(client: TestClient, session: Session, user: User) -> None:
    seed_library(session, user)
    snap = TopItemsSnapshot(
        user_id=user.id,
        kind=TopItemKind.track,
        time_range=TopTimeRange.short,
        captured_at=datetime(2024, 1, 1, tzinfo=UTC),
        items=[{"rank": 1, "spotify_id": "sp-t1", "name": "Track 1"}],
    )
    session.add(snap)
    session.commit()
    session.refresh(snap)

    timeline = client.get("/v1/taste/drift").json()
    assert len(timeline["timeline"]) == 1
    assert timeline["comparison"] is None

    compared = client.get(f"/v1/taste/drift?snapshot_id={snap.id}").json()
    assert compared["comparison"] is not None
    assert "axes" in compared["comparison"]


# ---------------------------------------------------------------- F4 flow arc


def _seed_reorderable(session: Session, user: User, fake: FakeSpotify) -> int:
    """A 4-track owned playlist mirrored into FakeSpotify, with features."""
    from crate.model.orm import Playlist, PlaylistTrack, Track

    sids = ["fa1", "fa2", "fa3", "fa4"]
    track_ids: list[int] = []
    for i, sid in enumerate(sids, start=1):
        row = Track(
            spotify_id=sid,
            name=f"Track {sid}",
            artists=[{"spotify_id": f"a-{sid}", "name": f"Artist {i}"}],
        )
        session.add(row)
        session.flush()
        track_ids.append(row.id)
        session.add(
            TrackFeatures(
                track_id=row.id,
                energy=i / 10,
                valence=i / 10,
                acousticness=i / 10,
                tempo=120.0,
                key=0,
                mode=1,
                status=FeatureStatus.present,
            )
        )
    playlist = Playlist(user_id=user.id, spotify_id="sp-Arc", name="Arc", is_owned=True)
    session.add(playlist)
    session.flush()
    for pos, track_id in enumerate(track_ids):
        session.add(
            PlaylistTrack(user_id=user.id, playlist_id=playlist.id, track_id=track_id, position=pos)
        )
    session.commit()
    fake.seed("sp-Arc", "Arc", [f"spotify:track:{s}" for s in sids])
    assert playlist.id is not None
    return playlist.id


def _local_order(session: Session, playlist_id: int) -> list[str]:
    from sqlmodel import col, select

    from crate.model.orm import PlaylistTrack, Track

    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(col(PlaylistTrack.position))
    ).all()
    return [track.spotify_id for _pt, track in rows]


def test_flow_arc_preview_is_read_only(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    playlist_id = _seed_reorderable(session, user, fake)
    before = _local_order(session, playlist_id)
    response = client.get(f"/v1/playlists/{playlist_id}/flow/arc?mood=rising")
    assert response.status_code == 200
    body = response.json()
    assert sorted(body["suggested_order"]) != []
    assert body["mood"] == "rising"
    assert body["suggested_flow"] is not None
    # Preview mutated nothing.
    assert _local_order(session, playlist_id) == before
    assert fake.write_calls == 0


def test_flow_arc_apply_is_journaled_and_undoable(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    playlist_id = _seed_reorderable(session, user, fake)
    before = _local_order(session, playlist_id)

    preview = client.get(f"/v1/playlists/{playlist_id}/flow/arc?mood=falling").json()
    suggested = preview["suggested_order"]

    apply_resp = client.post(
        f"/v1/playlists/{playlist_id}/flow/arc/apply",
        json={"order": suggested},
    )
    assert apply_resp.status_code == 200
    body = apply_resp.json()
    assert body["status"] == "applied"
    journal_id = body["journal_id"]
    assert body["_links"]["undo"]["href"] == f"/v1/journal/{journal_id}/undo"

    # The playlist now reflects the suggested order.
    from sqlmodel import select

    from crate.model.orm import Track

    id_to_sid = {
        t.id: t.spotify_id
        for t in session.exec(select(Track)).all()
        if t.spotify_id.startswith("fa")
    }
    assert _local_order(session, playlist_id) == [id_to_sid[tid] for tid in suggested]

    # Undo restores the original order.
    undo = client.post(f"/v1/journal/{journal_id}/undo")
    assert undo.status_code == 200
    session.expire_all()
    assert _local_order(session, playlist_id) == before
    entry = session.get(MutationJournal, journal_id)
    assert entry is not None and entry.status == MutationStatus.undone


def test_flow_arc_apply_stale_order_409(
    client: TestClient, session: Session, user: User, fake: FakeSpotify
) -> None:
    playlist_id = _seed_reorderable(session, user, fake)
    response = client.post(
        f"/v1/playlists/{playlist_id}/flow/arc/apply",
        json={"order": [999, 998]},  # not a permutation of the playlist
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "ORDER_STALE"
