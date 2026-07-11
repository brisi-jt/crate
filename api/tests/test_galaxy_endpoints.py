"""Artist-galaxy endpoint tests over a hand-computed micro-fixture.

Fixture: 6 tracks / 4 artists / 4 playlists (one followed).

  Credits: t1=[A]  t2=[A,B]  t3=[B]  t4=[C]  t5=[A,C]  t6=[D]
  Features on t1..t5 with value i/10 -> library percentile ranks are exactly
  0.1, 0.3, 0.5, 0.7, 0.9 (same convention as test_analytics_endpoints).

  P1 (owned)    = [t1, t2]      artists {A, B}
  P2 (owned)    = [t3, t4]      artists {B, C}
  P3 (owned)    = [t5]          artists {A, C}
  F1 (followed) = [t6]          artists {D}

Hand-derived truths (owned scope):
  A: tracks {t1,t2,t5} (3), playlists {P1,P3} (2),
     centroid = mean(0.1, 0.3, 0.9) = 0.4333 on every centroid feature
  B: tracks {t2,t3} (2), playlists {P1,P2}
  C: tracks {t4,t5} (2), playlists {P2,P3}
  Co-playlist edges: (a,b)=1 via P1, (b,c)=1 via P2, (a,c)=1 via P3
  Similarity: A->B 0.8 stays (both on the map); A->Zeta drops from edges but
  still shows on A's similar-artists list with in_library=False.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import (
    FeatureSource,
    FeatureStatus,
    PlaylistSyncStatus,
    SimilaritySource,
    SnapshotKind,
)
from crate.model.orm import (
    AnalyticsSnapshot,
    Artist,
    ArtistGenre,
    ArtistSimilarity,
    Genre,
    Playlist,
    PlaylistTrack,
    Track,
    TrackFeatures,
    User,
    utcnow,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


CREDITS = {
    1: ["Artist A"],
    2: ["Artist A", "Artist B"],
    3: ["Artist B"],
    4: ["Artist C"],
    5: ["Artist A", "Artist C"],
    6: ["Artist D"],
}


def seed_galaxy(session: Session, user: User) -> dict[str, int]:
    ids: dict[str, int] = {}

    tracks: dict[int, Track] = {}
    for i in range(1, 7):
        track = Track(
            spotify_id=f"sp-t{i}",
            isrc=f"ISRC0000000{i}",
            name=f"Track {i}",
            artists=[
                {"spotify_id": f"sp-{name.lower().replace(' ', '-')}", "name": name}
                for name in CREDITS[i]
            ],
            album_name="Album",
            duration_ms=180_000,
        )
        session.add(track)
        session.flush()
        tracks[i] = track
        assert track.id is not None
        ids[f"t{i}"] = track.id

    for i in range(1, 6):
        session.add(
            TrackFeatures(
                track_id=tracks[i].id,
                energy=i / 10,
                valence=i / 10,
                danceability=i / 10,
                acousticness=i / 10,
                instrumentalness=i / 10,
                liveness=i / 10,
                speechiness=i / 10,
                tempo=100.0 + i,
                loudness=-10.0 + i,
                key=0,
                mode=1,
                status=FeatureStatus.present,
                source=FeatureSource.reccobeats,
            )
        )

    def playlist(name: str, track_indexes: list[int], owned: bool = True) -> None:
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
        ids[name] = row.id
        for position, i in enumerate(track_indexes):
            session.add(
                PlaylistTrack(
                    user_id=user.id,
                    playlist_id=row.id,
                    track_id=tracks[i].id,
                    position=position,
                )
            )

    playlist("P1", [1, 2])
    playlist("P2", [3, 4])
    playlist("P3", [5])
    playlist("F1", [6], owned=False)

    # Catalog rows exist only for A and B — C and D must still make the map.
    artist_a = Artist(spotify_id="sp-artist-a", name="Artist A")
    artist_b = Artist(spotify_id="sp-artist-b", name="Artist B")
    session.add(artist_a)
    session.add(artist_b)
    session.flush()
    assert artist_a.id is not None and artist_b.id is not None
    session.add(
        ArtistSimilarity(
            artist_id=artist_a.id,
            similar_artist_id=artist_b.id,
            similar_artist_name="Artist B",
            weight=0.8,
            source=SimilaritySource.lastfm,
        )
    )
    session.add(
        ArtistSimilarity(
            artist_id=artist_a.id,
            similar_artist_name="Zeta",
            weight=0.6,
            source=SimilaritySource.lastfm,
        )
    )

    genre_1 = Genre(name="ambient techno", enao_rank=5)
    genre_2 = Genre(name="dub", enao_rank=9)
    session.add(genre_1)
    session.add(genre_2)
    session.flush()
    assert genre_1.id is not None and genre_2.id is not None
    # ENAO stores lowercase names — matching must be case-insensitive.
    session.add(ArtistGenre(genre_id=genre_1.id, artist_name="artist a", weight=100.0))
    session.add(ArtistGenre(genre_id=genre_1.id, artist_name="Zeta", weight=40.0))
    session.add(ArtistGenre(genre_id=genre_2.id, artist_name="Artist A", weight=60.0))
    session.commit()
    return ids


def node_by_name(body: dict, name: str) -> dict:
    matches = [n for n in body["nodes"] if n["name"] == name]
    assert len(matches) == 1, f"expected one node named {name}"
    return matches[0]


def test_galaxy_nodes_cover_owned_artists_with_reach_and_tracks(
    client: TestClient, session: Session, user: User
):
    ids = seed_galaxy(session, user)
    body = client.get("/v1/graph/artists").json()

    assert [n["name"] for n in body["nodes"]] == ["Artist A", "Artist B", "Artist C"]

    a = node_by_name(body, "Artist A")
    assert a["id"] == "artist a"
    assert a["track_count"] == 3
    assert a["playlist_count"] == 2
    assert sorted(a["playlist_ids"]) == sorted([ids["P1"], ids["P3"]])
    assert [t["name"] for t in a["tracks"]] == ["Track 1", "Track 2", "Track 5"]

    b = node_by_name(body, "Artist B")
    assert b["track_count"] == 2
    assert sorted(b["playlist_ids"]) == sorted([ids["P1"], ids["P2"]])


def test_galaxy_centroid_is_mean_track_percentile(client: TestClient, session: Session, user: User):
    seed_galaxy(session, user)
    body = client.get("/v1/graph/artists").json()
    a = node_by_name(body, "Artist A")
    for feature in ("acousticness", "energy", "valence"):
        assert a["centroid"][feature] == pytest.approx(0.4333, abs=1e-4)


def test_galaxy_edges_carry_kind_and_weight(client: TestClient, session: Session, user: User):
    seed_galaxy(session, user)
    body = client.get("/v1/graph/artists").json()

    co = {
        (e["source"], e["target"]): e["weight"] for e in body["edges"] if e["kind"] == "co_playlist"
    }
    assert co == {
        ("artist a", "artist b"): 1.0,
        ("artist a", "artist c"): 1.0,
        ("artist b", "artist c"): 1.0,
    }

    similarity = [e for e in body["edges"] if e["kind"] == "similarity"]
    assert similarity == [
        {"source": "artist a", "target": "artist b", "kind": "similarity", "weight": 0.8}
    ]


def test_galaxy_genres_and_similar_artists_on_nodes(
    client: TestClient, session: Session, user: User
):
    seed_galaxy(session, user)
    body = client.get("/v1/graph/artists").json()

    a = node_by_name(body, "Artist A")
    assert a["genres"] == ["ambient techno", "dub"]  # by ENAO weight
    assert a["similar"] == [
        {"name": "Artist B", "weight": 0.8, "in_library": True},
        {"name": "Zeta", "weight": 0.6, "in_library": False},
    ]

    # C has no catalog Artist row: still a node, just without similarity data.
    c = node_by_name(body, "Artist C")
    assert c["similar"] == []
    assert c["genres"] == []


def test_galaxy_full_scope_includes_followed_artists(
    client: TestClient, session: Session, user: User
):
    seed_galaxy(session, user)
    body = client.get("/v1/graph/artists", params={"owned_only": False}).json()
    names = [n["name"] for n in body["nodes"]]
    assert "Artist D" in names
    d = node_by_name(body, "Artist D")
    assert d["centroid"] is None  # t6 has no features

    owned = client.get("/v1/graph/artists").json()
    assert "Artist D" not in [n["name"] for n in owned["nodes"]]


def test_galaxy_coverage_reports_cap_state(client: TestClient, session: Session, user: User):
    seed_galaxy(session, user)
    body = client.get("/v1/graph/artists").json()
    assert body["coverage"] == {
        "artists_total": 3,
        "artists_shown": 3,
        "edges_total": 4,
        "edges_shown": 4,
    }
    assert body["_links"]["self"]["href"] == "/v1/graph/artists"


def test_galaxy_is_snapshot_cached(client: TestClient, session: Session, user: User):
    seed_galaxy(session, user)
    first = client.get("/v1/graph/artists").json()

    row = session.exec(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.kind == SnapshotKind.artist_galaxy)
    ).first()
    assert row is not None
    assert row.owned_only is True

    # New data lands without a sync pass — the cached payload holds.
    track = Track(spotify_id="sp-new", name="New", artists=[{"name": "Artist E"}])
    session.add(track)
    session.commit()
    assert client.get("/v1/graph/artists").json() == first
