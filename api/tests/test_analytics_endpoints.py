"""Analytics endpoint tests over the hand-computed micro-fixture.

Fixture: 6 tracks, 3 playlists. Tracks t1..t5 carry features whose value
increases with the index, so their library percentile ranks are exactly
0.1, 0.3, 0.5, 0.7, 0.9 (mean-rank over n=5). t6 has no features.

  Alpha = [t1, t2, t3, t4]
  Beta  = [t3, t4, t5]
  Gamma = [t1, t2, t3, t4, t5, t6]

Hand-derived truths asserted below:
  Alpha-Beta:  shared 2, containment 2/3       -> no subset
  Alpha-Gamma: shared 4, containment 4/4 = 1.0 -> subset
  Beta-Gamma:  shared 3, containment 3/3 = 1.0 -> subset
  Alpha centroid = mean(0.1, 0.3, 0.5, 0.7) = 0.4 on every feature
  Alpha cohesion = mean pairwise |rank diff| = 2.0/6 = 0.33333
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import FeatureSource, FeatureStatus, PlaylistSyncStatus, SnapshotKind
from crate.model.orm import (
    AnalyticsSnapshot,
    Playlist,
    PlaylistTrack,
    Track,
    TrackFeatures,
    User,
    utcnow,
)
from crate.services.analytics import engine

pytestmark = pytest.mark.unit

# Track index -> added_at quarter used by the temporal fixtures.
ADDED_AT = {
    1: datetime(2025, 1, 10),
    2: datetime(2025, 1, 20),
    3: datetime(2025, 4, 10),
    4: datetime(2025, 4, 20),
    5: datetime(2025, 7, 10),
    6: datetime(2025, 7, 20),
}


@pytest.fixture
def client(session: Session, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def seed_library(session: Session, user: User) -> dict[str, int]:
    """The module-docstring fixture; returns name -> id for playlists and tracks."""
    ids: dict[str, int] = {}

    tracks: dict[int, Track] = {}
    for i in range(1, 7):
        # t5 and t6 share an ISRC under different Spotify ids — the duplicate.
        isrc = "ISRCDUP00001" if i in (5, 6) else f"ISRC0000000{i}"
        track = Track(
            spotify_id=f"sp-t{i}",
            isrc=isrc,
            name=f"Track {i}",
            artists=[{"spotify_id": f"sp-a{i}", "name": f"Artist {i}"}],
            album_name="Album",
            duration_ms=180_000,
        )
        session.add(track)
        session.flush()
        tracks[i] = track
        assert track.id is not None
        ids[f"t{i}"] = track.id

    # Features for t1..t5 only. Every calibrated feature of track i carries
    # the value i (scaled where a plausible range matters), so each track's
    # percentile rank is identical across features: 0.1, 0.3, 0.5, 0.7, 0.9.
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

    def playlist(name: str, track_indexes: list[int]) -> None:
        row = Playlist(
            user_id=user.id,
            spotify_id=f"sp-{name}",
            name=name,
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
                    added_at=ADDED_AT[i],
                )
            )

    playlist("Alpha", [1, 2, 3, 4])
    playlist("Beta", [3, 4, 5])
    playlist("Gamma", [1, 2, 3, 4, 5, 6])
    session.commit()
    return ids


def seed_followed(session: Session, user: User, ids: dict[str, int]) -> int:
    """A followed (not owned) playlist "Radar" = [t3, t4, t5, t7].

    t7 exists only here, with features, so the reachable track set differs
    between the owned and full scopes. Radar's adds all land in 2026Q1 — a
    quarter no owned playlist touches.

    Hand-derived edges when Radar is in scope:
      Alpha-Radar: shared 2, containment 2/4       -> no subset
      Beta-Radar:  shared 3, containment 3/3 = 1.0 -> subset
      Gamma-Radar: shared 3, containment 3/4       -> no subset
    """
    t7 = Track(
        spotify_id="sp-t7",
        isrc="ISRC00000007",
        name="Track 7",
        artists=[{"spotify_id": "sp-a7", "name": "Artist 7"}],
        album_name="Album",
        duration_ms=180_000,
    )
    session.add(t7)
    session.flush()
    assert t7.id is not None
    ids["t7"] = t7.id
    session.add(
        TrackFeatures(
            track_id=t7.id,
            energy=0.65,
            valence=0.65,
            danceability=0.65,
            acousticness=0.65,
            instrumentalness=0.65,
            liveness=0.65,
            speechiness=0.65,
            tempo=107.0,
            loudness=-3.0,
            key=0,
            mode=1,
            status=FeatureStatus.present,
            source=FeatureSource.reccobeats,
        )
    )

    radar = Playlist(
        user_id=user.id,
        spotify_id="sp-Radar",
        name="Radar",
        snapshot_id="snap",
        is_owned=False,
        status=PlaylistSyncStatus.synced,
        last_synced_at=utcnow(),
    )
    session.add(radar)
    session.flush()
    assert radar.id is not None
    ids["Radar"] = radar.id
    for position, track_id in enumerate([ids["t3"], ids["t4"], ids["t5"], t7.id]):
        session.add(
            PlaylistTrack(
                user_id=user.id,
                playlist_id=radar.id,
                track_id=track_id,
                position=position,
                added_at=datetime(2026, 1, 15),
            )
        )
    session.commit()
    return radar.id


# ------------------------------------------------------------------- graph


def test_graph_shape_matches_web_contract(client: TestClient, session: Session, user: User):
    seed_library(session, user)
    body = client.get("/v1/graph/playlists").json()

    assert set(body) == {"nodes", "edges", "coverage", "_links"}
    for node in body["nodes"]:
        assert set(node) == {"id", "name", "track_count", "centroid"}
    for edge in body["edges"]:
        assert set(edge) == {"source", "target", "shared", "subset"}
    assert set(body["coverage"]) == {"enriched_tracks", "total_tracks"}


def test_graph_nodes_and_hand_computed_centroids(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    body = client.get("/v1/graph/playlists").json()

    nodes = {node["id"]: node for node in body["nodes"]}
    alpha = nodes[ids["Alpha"]]
    assert alpha["track_count"] == 4
    for feature in ("acousticness", "energy", "valence"):
        assert alpha["centroid"][feature] == pytest.approx(0.4)
    beta = nodes[ids["Beta"]]
    for feature in ("acousticness", "energy", "valence"):
        assert beta["centroid"][feature] == pytest.approx(0.7)
    # Gamma includes the unenriched t6, which simply doesn't contribute.
    gamma = nodes[ids["Gamma"]]
    for feature in ("acousticness", "energy", "valence"):
        assert gamma["centroid"][feature] == pytest.approx(0.5)

    assert body["coverage"] == {"enriched_tracks": 5, "total_tracks": 6}


def test_graph_edges_shared_counts_and_subset_flags(
    client: TestClient, session: Session, user: User
):
    ids = seed_library(session, user)
    body = client.get("/v1/graph/playlists").json()

    edges = {(edge["source"], edge["target"]): edge for edge in body["edges"]}
    assert len(edges) == 3
    ab = edges[(ids["Alpha"], ids["Beta"])]
    assert ab["shared"] == 2 and not ab["subset"]
    ag = edges[(ids["Alpha"], ids["Gamma"])]
    assert ag["shared"] == 4 and ag["subset"]
    bg = edges[(ids["Beta"], ids["Gamma"])]
    assert bg["shared"] == 3 and bg["subset"]


def test_graph_centroid_null_until_enrichment(client: TestClient, session: Session, user: User):
    row = Playlist(
        user_id=user.id,
        spotify_id="sp-empty",
        name="Empty",
        status=PlaylistSyncStatus.synced,
    )
    session.add(row)
    session.commit()
    body = client.get("/v1/graph/playlists").json()
    assert body["nodes"][0]["centroid"] is None


# ------------------------------------------------- playlist analytics + flow


def test_playlist_analytics_hand_computed(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    body = client.get(f"/v1/playlists/{ids['Alpha']}/analytics").json()

    assert set(body) == {"cohesion", "outliers", "overlaps", "fingerprint", "flow", "_links"}
    # mean pairwise |rank diff| over ranks {0.1, 0.3, 0.5, 0.7}
    assert body["cohesion"] == pytest.approx(0.3333, abs=1e-4)

    # Perfectly correlated features -> singular covariance -> Euclidean
    # fallback: distance = 3 * |rank - 0.4|; t1 and t4 tie at 0.9.
    assert [o["track_id"] for o in body["outliers"]] == [
        ids["t1"],
        ids["t4"],
        ids["t2"],
        ids["t3"],
    ]
    assert body["outliers"][0]["distance"] == pytest.approx(0.9, abs=1e-4)
    assert body["outliers"][0]["name"] == "Track 1"
    assert body["outliers"][0]["artist"] == "Artist 1"

    # Overlaps sorted by shared desc: Gamma (4) before Beta (2).
    assert [(o["playlist_id"], o["shared"]) for o in body["overlaps"]] == [
        (ids["Gamma"], 4),
        (ids["Beta"], 2),
    ]
    assert body["overlaps"][0]["containment"] == pytest.approx(1.0)
    assert body["overlaps"][1]["containment"] == pytest.approx(2 / 3, abs=1e-4)

    assert len(body["fingerprint"]) == 9
    for entry in body["fingerprint"]:
        assert entry["percentile"] == pytest.approx(0.4, abs=1e-4)

    # All tracks share key/mode; tempos within a few BPM -> near-perfect flow.
    assert body["flow"]["score"] > 90


def test_playlist_analytics_404_for_unknown_playlist(client: TestClient):
    response = client.get("/v1/playlists/999/analytics")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["error_code"] == "PLAYLIST_NOT_FOUND"


def test_flow_endpoint_transitions_and_suggestion(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    body = client.get(f"/v1/playlists/{ids['Beta']}/flow").json()

    assert set(body) == {"score", "transitions", "suggested_order", "suggested_score", "_links"}
    assert len(body["transitions"]) == 2
    assert body["score"] is not None and 0 <= body["score"] <= 100
    assert sorted(body["suggested_order"]) == sorted([ids["t3"], ids["t4"], ids["t5"]])
    assert body["suggested_score"] >= body["score"]


def test_flow_of_tiny_playlist_has_no_suggestion(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    playlist = Playlist(
        user_id=user.id, spotify_id="sp-solo", name="Solo", status=PlaylistSyncStatus.synced
    )
    session.add(playlist)
    session.flush()
    session.add(
        PlaylistTrack(user_id=user.id, playlist_id=playlist.id, track_id=ids["t1"], position=0)
    )
    session.commit()
    body = client.get(f"/v1/playlists/{playlist.id}/flow").json()
    assert body["score"] is None
    assert body["transitions"] == []
    assert body["suggested_order"] is None


# ------------------------------------------------------ temporal + library


def test_temporal_drift_and_growth(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    body = client.get("/v1/analytics/temporal").json()

    assert set(body) == {"drift", "growth", "_links"}
    # Q1 adds: t1 and t2 into Alpha and Gamma -> ranks (0.1, 0.3) twice.
    q1 = body["drift"][0]
    assert q1["quarter"] == "2025Q1"
    assert q1["energy"] == pytest.approx(0.2, abs=1e-4)
    assert q1["valence"] == pytest.approx(0.2, abs=1e-4)
    assert q1["acousticness"] == pytest.approx(0.2, abs=1e-4)
    # Q3 adds with features: t5 into Beta and Gamma (t6 has none) -> 0.9.
    q3 = body["drift"][2]
    assert q3["quarter"] == "2025Q3"
    assert q3["energy"] == pytest.approx(0.9, abs=1e-4)

    growth = {curve["playlist_id"]: curve for curve in body["growth"]}
    alpha_points = growth[ids["Alpha"]]["points"]
    assert [(p["quarter"], p["track_count"]) for p in alpha_points] == [
        ("2025Q1", 2),
        ("2025Q2", 4),
        ("2025Q3", 4),
    ]


def test_library_stats_duplicates_and_null_clusters(
    client: TestClient, session: Session, user: User
):
    seed_library(session, user)
    body = client.get("/v1/analytics/library").json()

    assert set(body) == {"drift", "duplicates", "clusters", "_links"}
    assert len(body["duplicates"]) == 1
    duplicate = body["duplicates"][0]
    assert duplicate["isrc"] == "ISRCDUP00001"
    # t5 lives in Beta and Gamma; t6 in Gamma.
    assert sorted(duplicate["playlists"]) == ["Beta", "Gamma"]
    # 5 enriched tracks is below the projection minimum -> no cluster summary.
    assert body["clusters"] is None
    assert body["drift"][0]["quarter"] == "2025Q1"


def test_map_endpoint_empty_library_shape(client: TestClient, session: Session, user: User):
    seed_library(session, user)
    body = client.get("/v1/map/tracks").json()
    assert set(body) == {
        "points",
        "cluster_count",
        "noise_count",
        "ari",
        "split_suggestions",
        "merge_suggestions",
        "layout_hash",
        "_links",
    }
    # 5 enriched tracks < the 10-track projection minimum.
    assert body["points"] == []
    assert body["layout_hash"] is None


# ----------------------------------------------------- caching + recompute


def test_reads_are_cached_until_recompute(client: TestClient, session: Session, user: User):
    seed_library(session, user)
    first = client.get("/v1/graph/playlists").json()
    assert len(first["nodes"]) == 3

    # New playlist lands without a sync pass — the cached payload holds.
    session.add(
        Playlist(user_id=user.id, spotify_id="sp-new", name="New", status=PlaylistSyncStatus.synced)
    )
    session.commit()
    assert len(client.get("/v1/graph/playlists").json()["nodes"]) == 3

    response = client.post("/v1/analytics/recompute")
    assert response.status_code == 200
    counts = response.json()
    assert counts["invalidated"] >= 1
    # 4 library payloads + (analytics + flow) per playlist.
    assert counts["computed"] == 4 + 2 * 4

    assert len(client.get("/v1/graph/playlists").json()["nodes"]) == 4


def test_playlist_snapshots_are_scoped_per_playlist(
    client: TestClient, session: Session, user: User
):
    ids = seed_library(session, user)
    client.get(f"/v1/playlists/{ids['Alpha']}/analytics")
    client.get(f"/v1/playlists/{ids['Beta']}/analytics")
    rows = session.exec(select(AnalyticsSnapshot)).all()
    assert {(row.kind, row.playlist_id) for row in rows} == {
        ("playlist_analytics", ids["Alpha"]),
        ("playlist_analytics", ids["Beta"]),
    }


# ------------------------------------------------- owned vs followed scoping


def test_graph_builder_scopes_to_owned_playlists(session: Session, user: User):
    ids = seed_library(session, user)
    seed_followed(session, user, ids)

    owned = engine.compute_graph_payload(session, user)
    assert {node["name"] for node in owned["nodes"]} == {"Alpha", "Beta", "Gamma"}
    assert owned["coverage"] == {"enriched_tracks": 5, "total_tracks": 6}

    everything = engine.compute_graph_payload(session, user, owned_only=False)
    assert {node["name"] for node in everything["nodes"]} == {"Alpha", "Beta", "Gamma", "Radar"}
    # t7 is reachable only through Radar.
    assert everything["coverage"] == {"enriched_tracks": 6, "total_tracks": 7}


def test_graph_endpoint_excludes_followed_by_default(
    client: TestClient, session: Session, user: User
):
    ids = seed_library(session, user)
    radar_id = seed_followed(session, user, ids)

    body = client.get("/v1/graph/playlists").json()
    assert {node["id"] for node in body["nodes"]} == {ids["Alpha"], ids["Beta"], ids["Gamma"]}
    assert all(radar_id not in (edge["source"], edge["target"]) for edge in body["edges"])


def test_graph_endpoint_includes_followed_when_owned_only_false(
    client: TestClient, session: Session, user: User
):
    ids = seed_library(session, user)
    radar_id = seed_followed(session, user, ids)

    body = client.get("/v1/graph/playlists", params={"owned_only": False}).json()
    assert {node["id"] for node in body["nodes"]} == {
        ids["Alpha"],
        ids["Beta"],
        ids["Gamma"],
        radar_id,
    }
    edges = {(edge["source"], edge["target"]): edge for edge in body["edges"]}
    br = edges[tuple(sorted((ids["Beta"], radar_id)))]
    assert br["shared"] == 3 and br["subset"]


def test_temporal_scopes_followed_adds(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    seed_followed(session, user, ids)

    owned = client.get("/v1/analytics/temporal").json()
    assert all(point["quarter"] != "2026Q1" for point in owned["drift"])
    assert {curve["name"] for curve in owned["growth"]} == {"Alpha", "Beta", "Gamma"}

    everything = client.get("/v1/analytics/temporal", params={"owned_only": False}).json()
    assert any(point["quarter"] == "2026Q1" for point in everything["drift"])
    assert {curve["name"] for curve in everything["growth"]} == {"Alpha", "Beta", "Gamma", "Radar"}


def test_library_stats_scope_duplicates(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    seed_followed(session, user, ids)

    owned = client.get("/v1/analytics/library").json()
    assert sorted(owned["duplicates"][0]["playlists"]) == ["Beta", "Gamma"]

    everything = client.get("/v1/analytics/library", params={"owned_only": False}).json()
    assert sorted(everything["duplicates"][0]["playlists"]) == ["Beta", "Gamma", "Radar"]


def test_owned_playlist_overlaps_exclude_followed(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    radar_id = seed_followed(session, user, ids)

    body = client.get(f"/v1/playlists/{ids['Beta']}/analytics").json()
    assert radar_id not in [overlap["playlist_id"] for overlap in body["overlaps"]]


def test_followed_playlist_analytics_use_the_full_library(
    client: TestClient, session: Session, user: User
):
    ids = seed_library(session, user)
    radar_id = seed_followed(session, user, ids)

    body = client.get(f"/v1/playlists/{radar_id}/analytics").json()
    overlaps = {overlap["playlist_id"]: overlap for overlap in body["overlaps"]}
    assert overlaps[ids["Beta"]]["shared"] == 3

    row = session.exec(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.playlist_id == radar_id)
    ).one()
    assert row.owned_only is False


def test_snapshot_scopes_do_not_collide(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    seed_followed(session, user, ids)

    assert len(client.get("/v1/graph/playlists").json()["nodes"]) == 3
    assert len(client.get("/v1/graph/playlists", params={"owned_only": False}).json()["nodes"]) == 4

    rows = session.exec(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.kind == SnapshotKind.graph)
    ).all()
    assert {row.owned_only for row in rows} == {True, False}
    # Cached reads keep serving their own scope.
    assert len(client.get("/v1/graph/playlists").json()["nodes"]) == 3


def test_recompute_scopes_to_owned_by_default(client: TestClient, session: Session, user: User):
    ids = seed_library(session, user)
    radar_id = seed_followed(session, user, ids)

    counts = client.post("/v1/analytics/recompute").json()
    # 4 library payloads + (analytics + flow) per owned playlist.
    assert counts["computed"] == 4 + 2 * 3

    rows = session.exec(select(AnalyticsSnapshot)).all()
    assert all(row.owned_only for row in rows)
    assert radar_id not in {row.playlist_id for row in rows}


def test_recompute_all_scope_covers_followed_playlists(
    client: TestClient, session: Session, user: User
):
    ids = seed_library(session, user)
    radar_id = seed_followed(session, user, ids)

    counts = client.post("/v1/analytics/recompute", params={"owned_only": False}).json()
    # 4 full-scope library payloads + 2 per owned playlist + 2 for Radar.
    assert counts["computed"] == 4 + 2 * 3 + 2

    rows = session.exec(select(AnalyticsSnapshot)).all()
    per_playlist_scopes = {row.playlist_id: row.owned_only for row in rows if row.playlist_id}
    # Owned playlists stay keyed to the owned scope their reads use; Radar
    # (reachable only in the full scope) is keyed to it.
    assert per_playlist_scopes[ids["Alpha"]] is True
    assert per_playlist_scopes[radar_id] is False
    library_scopes = {row.owned_only for row in rows if row.playlist_id is None}
    assert library_scopes == {False}
