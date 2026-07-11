"""Full enrichment ladder against migrated MySQL: local DSP fills what
ReccoBeats missed, and the coverage numbers reflect it.

Real feature computation runs on synthetic in-test WAV audio served through a
mock CDN — no network, no golden values from real songs.
"""

import io

import httpx
import numpy as np
import pytest
import soundfile as sf
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user
from crate.model.enums import FeatureSource, FeatureStatus
from crate.model.orm import LocalDspCalibration, Track, TrackFeatures, User
from crate.services.enrichment.localdsp import LocalDspClient, PreviewCache
from crate.services.enrichment.models import AudioFeatures, DeezerTrack
from crate.services.enrichment.orchestrator import EnrichmentService
from tests.db_guard import drop_all_tables
from tests.test_enrichment_orchestrator import FakeMusicBrainz, FakeRecco
from tests.test_migrations_integration import alembic_config

pytestmark = pytest.mark.integration

SR = 22050
OVERLAP_COUNT = 8


def wav_bytes(seed: int, amp: float = 0.4, seconds: float = 1.5) -> bytes:
    rng = np.random.default_rng(seed)
    samples = (amp * rng.standard_normal(int(SR * seconds))).clip(-1, 1).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SR, format="WAV")
    return buffer.getvalue()


class MappedPreviewSearch:
    """Deezer stand-in: "title|artist" -> preview URL."""

    def __init__(self, previews: dict[str, str]) -> None:
        self.previews = previews

    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None:
        url = self.previews.get(f"{title.lower()}|{artist.lower()}")
        if url is None:
            return None
        return DeezerTrack(id=1, title=title, preview=url, artist_name=artist)


@pytest.fixture
def migrated_session(integration_engine: Engine):
    drop_all_tables(integration_engine)
    command.upgrade(alembic_config(), "head")
    with Session(integration_engine) as session:
        yield session


async def test_full_ladder_localdsp_fills_reccobeats_gaps(
    migrated_session: Session, tmp_path
) -> None:
    session = migrated_session
    artists = [{"spotify_id": "a-x", "name": "Artist X"}]
    # Eight tracks ReccoBeats knows (the calibration overlap set), two it
    # misses — one with a preview, one without any.
    recco_features = {}
    previews: dict[str, str] = {}
    audio_by_url: dict[str, bytes] = {}
    for i in range(OVERLAP_COUNT):
        session.add(Track(spotify_id=f"o{i}", name=f"Overlap {i}", artists=artists))
        recco_features[f"o{i}"] = AudioFeatures(
            energy=0.2 + i / 10, valence=0.4, tempo=100.0 + i, loudness=-10.0 - i
        )
        url = f"https://cdn.test/o{i}"
        previews[f"overlap {i}|artist x"] = url
        audio_by_url[url] = wav_bytes(seed=i, amp=0.1 + i / 20)
    session.add(Track(spotify_id="gap", name="Gap Track", artists=artists))
    previews["gap track|artist x"] = "https://cdn.test/gap"
    audio_by_url["https://cdn.test/gap"] = wav_bytes(seed=99, amp=0.3)
    session.add(Track(spotify_id="nopreview", name="Preview-less", artists=artists))
    session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=audio_by_url[str(request.url)])

    localdsp = LocalDspClient(
        previews=MappedPreviewSearch(previews),
        cache=PreviewCache(tmp_path / "previews", max_bytes=50_000_000),
        transport=httpx.MockTransport(handler),
    )
    try:
        service = EnrichmentService(
            reccobeats=FakeRecco(by_id=recco_features),
            musicbrainz=FakeMusicBrainz(),
            localdsp=localdsp,
        )
        report = await service.run(session, batch_size=50)
    finally:
        await localdsp.aclose()

    assert report.features_from_reccobeats == OVERLAP_COUNT
    assert report.features_from_localdsp == 1
    assert report.localdsp_no_preview == 1
    assert report.features_missing == 1  # only the preview-less track is left
    assert report.localdsp_uncalibrated is False

    gap_row = session.exec(select(TrackFeatures).join(Track).where(Track.spotify_id == "gap")).one()
    assert gap_row.status == FeatureStatus.present
    assert gap_row.source == FeatureSource.essentia
    assert gap_row.preview_resolved is True
    assert gap_row.local_raw is not None and "energy" in gap_row.local_raw
    assert gap_row.energy is not None

    bare_row = session.exec(
        select(TrackFeatures).join(Track).where(Track.spotify_id == "nopreview")
    ).one()
    assert bare_row.status == FeatureStatus.missing
    assert bare_row.preview_resolved is False

    calibrations = session.exec(select(LocalDspCalibration)).all()
    assert {c.feature for c in calibrations} >= {"energy", "tempo", "loudness"}

    # Coverage math through the real status endpoint: 9 of 10 covered.
    user = User(clerk_user_id="dsp-int-user")
    session.add(user)
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    status = TestClient(app).get("/v1/enrichment/status").json()

    assert status["tracks_total"] == 10
    assert status["tracks_with_features"] == 9
    assert status["tracks_missing_features"] == 1
    assert status["feature_coverage_pct"] == pytest.approx(90.0)
    assert status["features_by_source"]["reccobeats"] == OVERLAP_COUNT
    assert status["features_by_source"]["essentia"] == 1
    assert status["local_dsp"]["analyzed"] == 1
    assert status["local_dsp"]["no_preview"] == 1
    assert status["local_dsp"]["queued"] == 0
    # 10 preview lookups ran (8 overlap + gap + preview-less); 9 found audio.
    assert status["local_dsp"]["preview_resolution_pct"] == pytest.approx(90.0)
