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
    async def fake_runner(
        _session: Session,
        batch_size: int,
        *,
        time_budget_seconds: float = 240.0,
        stage: str = "feature",
    ) -> EnrichmentReport:
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


def seed_features(
    session: Session,
    track: Track,
    status: FeatureStatus,
    source: FeatureSource | None = None,
    preview_resolved: bool | None = None,
) -> None:
    if source is None and status == FeatureStatus.present:
        source = FeatureSource.reccobeats
    session.add(
        TrackFeatures(
            track_id=track.id,
            status=status,
            source=source,
            energy=0.5 if status == FeatureStatus.present else None,
            preview_resolved=preview_resolved,
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


class TestRunParams:
    def test_stage_param_is_passed_through(self, session: Session, user: User) -> None:
        seen: dict = {}

        async def runner(
            _session: Session,
            batch_size: int,
            *,
            time_budget_seconds: float,
            stage: str,
        ) -> EnrichmentReport:
            seen["batch_size"] = batch_size
            seen["time_budget_seconds"] = time_budget_seconds
            seen["stage"] = stage
            return EnrichmentReport()

        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_enrichment_runner] = lambda: runner
        resp = TestClient(app).post(
            "/v1/enrichment/run", params={"stage": "identity", "time_budget_seconds": 120}
        )

        assert resp.status_code == 200
        assert seen["stage"] == "identity"
        assert seen["time_budget_seconds"] == 120

    def test_default_stage_is_feature_and_budget_default_applied(
        self, session: Session, user: User
    ) -> None:
        seen: dict = {}

        async def runner(
            _session: Session, batch_size: int, *, time_budget_seconds: float, stage: str
        ) -> EnrichmentReport:
            seen["stage"] = stage
            seen["time_budget_seconds"] = time_budget_seconds
            return EnrichmentReport()

        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_enrichment_runner] = lambda: runner
        resp = TestClient(app).post("/v1/enrichment/run")

        assert resp.status_code == 200
        assert seen["stage"] == "feature"
        assert seen["time_budget_seconds"] == 240

    def test_invalid_stage_is_rejected(self, session: Session, user: User) -> None:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        resp = TestClient(app).post("/v1/enrichment/run", params={"stage": "bogus"})
        assert resp.status_code == 422

    def test_budget_over_cap_is_rejected(self, session: Session, user: User) -> None:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        resp = TestClient(app).post("/v1/enrichment/run", params={"time_budget_seconds": 9999})
        assert resp.status_code == 422

    def test_report_exposes_budget_and_stage_timing(self, session: Session, user: User) -> None:
        async def runner(
            _session: Session, batch_size: int, *, time_budget_seconds: float, stage: str
        ) -> EnrichmentReport:
            return EnrichmentReport(
                budget_exhausted=True,
                stage_seconds={"reccobeats": 1.5, "isrc_fallback": 12.0},
            )

        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_enrichment_runner] = lambda: runner
        body = TestClient(app).post("/v1/enrichment/run").json()

        assert body["budget_exhausted"] is True
        assert body["stage_seconds"]["isrc_fallback"] == 12.0


class TestSingleFlight:
    def test_concurrent_run_returns_409(self, session: Session, user: User) -> None:
        import anyio

        from crate.router import enrichment as enrichment_router

        # Reset the process-wide guard so the test is order-independent.
        enrichment_router.reset_active_passes()

        release = anyio.Event()
        entered = anyio.Event()

        async def blocking_runner(
            _session: Session, batch_size: int, *, time_budget_seconds: float, stage: str
        ) -> EnrichmentReport:
            entered.set()
            await release.wait()
            return EnrichmentReport()

        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_enrichment_runner] = lambda: blocking_runner

        from httpx import ASGITransport, AsyncClient

        async def scenario() -> tuple[int, int]:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://t") as ac:
                async with anyio.create_task_group() as tg:
                    first_status: list[int] = []

                    async def first() -> None:
                        r = await ac.post("/v1/enrichment/run")
                        first_status.append(r.status_code)

                    tg.start_soon(first)
                    await entered.wait()  # first pass is now holding the lock
                    second = await ac.post("/v1/enrichment/run")
                    release.set()
                return first_status[0], second.status_code

        first_code, second_code = anyio.run(scenario)
        assert first_code == 200
        assert second_code == 409

    def test_409_carries_problem_json_and_code(self, session: Session, user: User) -> None:
        from crate.router import enrichment as enrichment_router

        enrichment_router.reset_active_passes()
        assert user.id is not None
        enrichment_router.mark_active(user.id)  # simulate an in-flight pass
        try:
            app = create_app()
            app.dependency_overrides[get_session] = lambda: session
            app.dependency_overrides[get_current_user] = lambda: user
            resp = TestClient(app).post("/v1/enrichment/run")
            assert resp.status_code == 409
            assert resp.headers["content-type"].startswith("application/problem+json")
            assert resp.json()["error_code"] == "ENRICHMENT_PASS_ACTIVE"
        finally:
            enrichment_router.reset_active_passes()


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

    def test_per_source_counts_and_local_dsp_block(
        self, client: TestClient, session: Session
    ) -> None:
        recco = seed_track(session, "r1")
        seed_features(session, recco, FeatureStatus.present)
        local = seed_track(session, "l1")
        seed_features(
            session,
            local,
            FeatureStatus.present,
            source=FeatureSource.essentia,
            preview_resolved=True,
        )
        no_preview = seed_track(session, "n1")
        seed_features(session, no_preview, FeatureStatus.missing, preview_resolved=False)
        queued = seed_track(session, "q1")
        seed_features(session, queued, FeatureStatus.missing)

        body = client.get("/v1/enrichment/status").json()

        assert body["features_by_source"] == {"reccobeats": 1, "freqblog": 0, "essentia": 1}
        dsp = body["local_dsp"]
        assert dsp["enabled"] is True
        assert dsp["analyzed"] == 1
        assert dsp["queued"] == 1  # missing, preview never looked for
        assert dsp["no_preview"] == 1
        # Two preview lookups ever attempted, one found audio.
        assert dsp["preview_resolution_pct"] == pytest.approx(50.0)

    def test_local_dsp_rate_is_null_before_any_attempt(self, client: TestClient) -> None:
        body = client.get("/v1/enrichment/status").json()
        assert body["local_dsp"]["preview_resolution_pct"] is None
        assert body["local_dsp"]["analyzed"] == 0


class TestRunEndpointLocalDsp:
    def test_run_reports_localdsp_counts(
        self, session: Session, user: User, run_calls: list[int]
    ) -> None:
        async def runner(
            _session: Session,
            batch_size: int,
            *,
            time_budget_seconds: float = 240.0,
            stage: str = "feature",
        ) -> EnrichmentReport:
            run_calls.append(batch_size)
            return EnrichmentReport(
                tracks_processed=2,
                features_from_localdsp=1,
                localdsp_no_preview=1,
                localdsp_uncalibrated=True,
                errors=["localdsp t-x: decode failed"],
            )

        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_enrichment_runner] = lambda: runner
        body = TestClient(app).post("/v1/enrichment/run").json()

        assert body["features_from_localdsp"] == 1
        assert body["localdsp_no_preview"] == 1
        assert body["localdsp_uncalibrated"] is True
        assert body["localdsp_skipped"] is False
        assert body["errors"] == ["localdsp t-x: decode failed"]
