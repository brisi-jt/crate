"""Enrichment endpoints: run trigger and coverage status, fully offline."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_enrichment_runner
from crate.model.enums import FeatureSource, FeatureStatus, SimilaritySource, TagSource
from crate.model.orm import Artist, ArtistSimilarity, ArtistTag, Track, TrackFeatures, User
from crate.services.enrichment.orchestrator import EnrichmentReport

pytestmark = pytest.mark.unit


@pytest.fixture
def run_calls() -> list[int]:
    return []


@pytest.fixture
def client(session: Session, user: User, run_calls: list[int]) -> TestClient:
    async def fake_runner(_session: Session, batch_size: int) -> EnrichmentReport:
        run_calls.append(batch_size)
        return EnrichmentReport(
            tracks_processed=3,
            features_from_reccobeats=2,
            features_from_freqblog=1,
            lastfm_skipped=True,
        )

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_enrichment_runner] = lambda: fake_runner
    return TestClient(app)


def seed_track(session: Session, spotify_id: str) -> Track:
    track = Track(spotify_id=spotify_id, name=spotify_id, artists=[])
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def seed_features(session: Session, track: Track, status: FeatureStatus) -> None:
    session.add(
        TrackFeatures(
            track_id=track.id,
            status=status,
            source=FeatureSource.reccobeats if status == FeatureStatus.present else None,
            energy=0.5 if status == FeatureStatus.present else None,
        )
    )
    session.commit()


def seed_artist(session: Session, spotify_id: str, **kwargs) -> Artist:
    artist = Artist(spotify_id=spotify_id, name=f"Artist {spotify_id}", **kwargs)
    session.add(artist)
    session.commit()
    session.refresh(artist)
    return artist


class TestRunEndpoint:
    def test_run_returns_report_with_links(self, client: TestClient) -> None:
        response = client.post("/v1/enrichment/run")
        assert response.status_code == 200
        body = response.json()
        assert body["tracks_processed"] == 3
        assert body["features_from_reccobeats"] == 2
        assert body["features_from_freqblog"] == 1
        assert body["lastfm_skipped"] is True
        assert body["_links"]["status"]["href"] == "/v1/enrichment/status"

    def test_batch_size_param_is_passed_through(
        self, client: TestClient, run_calls: list[int]
    ) -> None:
        response = client.post("/v1/enrichment/run", params={"batch_size": 25})
        assert response.status_code == 200
        assert run_calls == [25]

    def test_batch_size_is_validated(self, client: TestClient) -> None:
        response = client.post("/v1/enrichment/run", params={"batch_size": 0})
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")


class TestStatusEndpoint:
    def test_empty_library_reports_zero_coverage(self, client: TestClient) -> None:
        response = client.get("/v1/enrichment/status")
        assert response.status_code == 200
        body = response.json()
        assert body["tracks_total"] == 0
        assert body["feature_coverage_pct"] == 0.0
        assert body["_links"]["self"]["href"] == "/v1/enrichment/status"
        assert body["_links"]["run"]["href"] == "/v1/enrichment/run"

    def test_feature_coverage_percentages(self, client: TestClient, session: Session) -> None:
        present = seed_track(session, "p1")
        seed_features(session, present, FeatureStatus.present)
        missing = seed_track(session, "m1")
        seed_features(session, missing, FeatureStatus.missing)
        seed_track(session, "unprocessed")

        body = client.get("/v1/enrichment/status").json()

        assert body["tracks_total"] == 3
        assert body["tracks_with_features"] == 1
        assert body["tracks_missing_features"] == 1
        assert body["tracks_pending"] == 1
        assert body["feature_coverage_pct"] == pytest.approx(33.3, abs=0.1)

    def test_artist_coverage_and_pending_lastfm(self, client: TestClient, session: Session) -> None:
        tagged = seed_artist(session, "a1", mbid="mbid-1")
        session.add(
            ArtistSimilarity(
                artist_id=tagged.id,
                similar_artist_name="Other",
                weight=0.5,
                source=SimilaritySource.lastfm,
            )
        )
        session.add(
            ArtistTag(artist_id=tagged.id, tag="electronic", weight=90, source=TagSource.lastfm)
        )
        session.commit()
        seed_artist(session, "a2")

        body = client.get("/v1/enrichment/status").json()

        assert body["artists_total"] == 2
        assert body["artists_with_mbid"] == 1
        assert body["artists_with_similarity"] == 1
        assert body["artists_with_tags"] == 1
        assert body["similarity_coverage_pct"] == pytest.approx(50.0)
        # No Last.fm key in test settings: artist enrichment waits on one.
        assert body["lastfm"] == "pending"

    def test_freqblog_budget_reported(self, client: TestClient) -> None:
        body = client.get("/v1/enrichment/status").json()
        assert body["freqblog"]["limit"] == 1000
        assert body["freqblog"]["used"] == 0
        assert body["freqblog"]["configured"] is False
