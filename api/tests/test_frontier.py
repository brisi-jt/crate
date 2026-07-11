"""Frontier computation tests — every number hand-derivable.

Fixture (pure): library artists {alpha, beta}; five ENAO genres.

  house   (G1): alpha=100, x1=80,  x2=60      w_max=100
  techno  (G2): x1=100,   beta=50, x3=25      w_max=100
  electro (G3): x1=100,   x4=90                w_max=100
  ambient (G4): x5=100                         w_max=100
  minimal (G5): x2=100,   x6=50,  alpha=20     w_max=100

Presence (raw = sum of matched w/w_max; normalized by the max raw):
  G1: 100/100 = 1.0            -> presence 1.0
  G2: 50/100  = 0.5            -> presence 0.5
  G5: 20/100  = 0.2            -> presence 0.2
  G3, G4: 0

Territory = genres with any matched artist: G1, G2, G5 (presence order).

Adjacency (shared ENAO artists / smaller artist set):
  G3-G1: |{x1}|/min(2,3) = 0.5      G3-G2: |{x1}|/min(2,3) = 0.5
  G5-G1: |{alpha,x2}|/min(3,3) = 0.66667
  G4-*:  0

Frontier scores (eligible when presence < 0.5):
  G3: (0.5*1.0 + 0.5*0.5) * (1-0)   = 0.75
  G5: (0.66667*1.0)       * (1-0.2) = 0.53333
  G2: presence 0.5 -> not eligible.  G4: no adjacency -> score 0, dropped.

Exemplars exclude library artists:
  G3: x1 (1.0), x4 (0.9)     G5: x2 (1.0), x6 (0.5) — alpha excluded.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import PlaylistSyncStatus, SnapshotKind
from crate.model.orm import (
    AnalyticsSnapshot,
    ArtistGenre,
    Genre,
    Playlist,
    PlaylistTrack,
    Track,
    User,
    utcnow,
)
from crate.services.discovery.frontier import compute_frontier

pytestmark = pytest.mark.unit

GENRE_META = {
    1: ("house", 1),
    2: ("techno", 2),
    3: ("electro", 3),
    4: ("ambient", 4),
    5: ("minimal", 5),
}
GENRE_ARTISTS = {
    1: {"alpha": 100.0, "x1": 80.0, "x2": 60.0},
    2: {"x1": 100.0, "beta": 50.0, "x3": 25.0},
    3: {"x1": 100.0, "x4": 90.0},
    4: {"x5": 100.0},
    5: {"x2": 100.0, "x6": 50.0, "alpha": 20.0},
}
LIBRARY = {"alpha", "beta"}


def test_territory_ranked_by_presence():
    result = compute_frontier(GENRE_META, GENRE_ARTISTS, LIBRARY)
    territory = result["territory"]
    assert [(t["name"], t["presence"]) for t in territory] == [
        ("house", 1.0),
        ("techno", 0.5),
        ("minimal", 0.2),
    ]
    assert territory[0]["matched_artists"] == 1
    assert territory[0]["genre_id"] == 1
    assert territory[0]["enao_rank"] == 1


def test_frontier_scores_adjacent_weakly_represented_genres():
    result = compute_frontier(GENRE_META, GENRE_ARTISTS, LIBRARY)
    frontier = result["frontier"]
    assert [f["name"] for f in frontier] == ["electro", "minimal"]

    electro = frontier[0]
    assert electro["score"] == pytest.approx(0.75, abs=1e-4)
    assert electro["presence"] == 0.0
    assert electro["adjacent_to"] == ["house", "techno"]

    minimal = frontier[1]
    assert minimal["score"] == pytest.approx(0.5333, abs=1e-4)
    assert minimal["presence"] == 0.2
    assert minimal["adjacent_to"] == ["house"]


def test_frontier_excludes_established_and_unconnected_genres():
    result = compute_frontier(GENRE_META, GENRE_ARTISTS, LIBRARY)
    names = [f["name"] for f in result["frontier"]]
    assert "techno" not in names  # presence 0.5 — already represented
    assert "ambient" not in names  # shares no artists with the territory
    assert "house" not in names


def test_exemplars_exclude_library_artists_and_normalize_weight():
    result = compute_frontier(GENRE_META, GENRE_ARTISTS, LIBRARY)
    by_name = {f["name"]: f for f in result["frontier"]}
    assert by_name["electro"]["exemplars"] == [
        {"name": "x1", "weight": 1.0},
        {"name": "x4", "weight": 0.9},
    ]
    assert by_name["minimal"]["exemplars"] == [
        {"name": "x2", "weight": 1.0},
        {"name": "x6", "weight": 0.5},
    ]


def test_empty_library_yields_empty_frontier():
    result = compute_frontier(GENRE_META, GENRE_ARTISTS, set())
    assert result["territory"] == []
    assert result["frontier"] == []
    assert result["matched_artists"] == 0


def test_matched_artists_counts_library_names_found_in_enao():
    result = compute_frontier(GENRE_META, GENRE_ARTISTS, LIBRARY | {"nowhere"})
    assert result["matched_artists"] == 2


# ---------------------------------------------------------------- endpoint


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_frontier(session: Session, user: User) -> None:
    """The docstring fixture with Alpha owned and Beta only followed."""

    def track(i: int, artist: str) -> Track:
        row = Track(
            spotify_id=f"sp-t{i}",
            name=f"Track {i}",
            artists=[{"spotify_id": f"sp-{artist.lower()}", "name": artist}],
        )
        session.add(row)
        session.flush()
        return row

    def playlist(name: str, tracks: list[Track], owned: bool = True) -> None:
        row = Playlist(
            user_id=user.id,
            spotify_id=f"sp-{name}",
            name=name,
            is_owned=owned,
            snapshot_id="snap",
            status=PlaylistSyncStatus.synced,
            last_synced_at=utcnow(),
        )
        session.add(row)
        session.flush()
        assert row.id is not None
        for position, t in enumerate(tracks):
            session.add(
                PlaylistTrack(user_id=user.id, playlist_id=row.id, track_id=t.id, position=position)
            )

    playlist("Owned", [track(1, "Alpha")])
    playlist("Followed", [track(2, "Beta")], owned=False)

    for genre_id, (name, rank) in GENRE_META.items():
        genre = Genre(name=name, enao_rank=rank)
        session.add(genre)
        session.flush()
        for artist, weight in GENRE_ARTISTS[genre_id].items():
            session.add(ArtistGenre(genre_id=genre.id, artist_name=artist, weight=weight))
    session.commit()


def test_frontier_endpoint_owned_scope_drops_followed_artists(
    client: TestClient, session: Session, user: User
):
    seed_frontier(session, user)
    body = client.get("/v1/discovery/frontier").json()

    # Owned scope: only Alpha counts -> techno has no presence and becomes
    # frontier (adjacent to house via x1).
    assert [t["name"] for t in body["territory"]] == ["house", "minimal"]
    assert "techno" in [f["name"] for f in body["frontier"]]
    assert body["coverage"] == {"library_artists": 1, "matched_artists": 1}
    assert body["_links"]["self"]["href"] == "/v1/discovery/frontier"


def test_frontier_endpoint_full_scope_matches_hand_computation(
    client: TestClient, session: Session, user: User
):
    seed_frontier(session, user)
    body = client.get("/v1/discovery/frontier", params={"owned_only": False}).json()
    assert [t["name"] for t in body["territory"]] == ["house", "techno", "minimal"]
    frontier = {f["name"]: f for f in body["frontier"]}
    assert frontier["electro"]["score"] == pytest.approx(0.75, abs=1e-4)
    assert frontier["electro"]["exemplars"][0] == {"name": "x1", "weight": 1.0}
    assert body["coverage"] == {"library_artists": 2, "matched_artists": 2}


def test_frontier_endpoint_is_snapshot_cached(client: TestClient, session: Session, user: User):
    seed_frontier(session, user)
    first = client.get("/v1/discovery/frontier").json()

    row = session.exec(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.kind == SnapshotKind.frontier)
    ).first()
    assert row is not None

    session.add(Genre(name="new genre", enao_rank=99))
    session.commit()
    assert client.get("/v1/discovery/frontier").json() == first


def test_frontier_endpoint_empty_enao_layer(client: TestClient, session: Session, user: User):
    body = client.get("/v1/discovery/frontier").json()
    assert body["territory"] == []
    assert body["frontier"] == []
    assert body["coverage"] == {"library_artists": 0, "matched_artists": 0}
