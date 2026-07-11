"""Local DSP: synthetic-audio feature sanity, preview cache, client behavior.

Audio fixtures are generated in-test (sine, noise, click train, silence) —
directional assertions only, never golden values from real songs.
"""

import asyncio
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

import crate.services.enrichment.localdsp as localdsp
from crate.services.enrichment.localdsp import (
    LOCAL_FEATURES,
    LocalDspClient,
    PreviewCache,
    compute_features,
)
from crate.services.enrichment.models import DeezerTrack

pytestmark = pytest.mark.unit

SR = 22050


def write_wav(path: Path, samples: np.ndarray) -> Path:
    sf.write(str(path), samples.astype(np.float32), SR, format="WAV")
    return path


def sine(seconds: float = 3.0, freq: float = 440.0, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return amp * np.sin(2 * np.pi * freq * t)


def noise(seconds: float = 3.0, amp: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(42)
    return amp * rng.standard_normal(int(SR * seconds)).clip(-1, 1)


def click_train(seconds: float = 6.0, bpm: float = 120.0) -> np.ndarray:
    """Sharp decaying clicks on a rigid bpm grid."""
    y = np.zeros(int(SR * seconds))
    interval = int(SR * 60.0 / bpm)
    click_len = 256
    envelope = np.exp(-np.linspace(0, 8, click_len))
    for start in range(0, len(y) - click_len, interval):
        y[start : start + click_len] += envelope
    return 0.8 * y


@pytest.fixture(scope="module")
def wavs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("localdsp-audio")
    return {
        "sine": write_wav(base / "sine.wav", sine()),
        "noise": write_wav(base / "noise.wav", noise()),
        "quiet_noise": write_wav(base / "quiet.wav", noise(amp=0.02)),
        "clicks": write_wav(base / "clicks.wav", click_train()),
        "silence": write_wav(base / "silence.wav", np.zeros(SR * 2)),
    }


@pytest.fixture(scope="module")
def computed(wavs: dict[str, Path]) -> dict[str, dict[str, float]]:
    return {name: compute_features(path) for name, path in wavs.items()}


class TestComputeFeatures:
    def test_every_feature_present_and_bounded(self, computed: dict[str, dict[str, float]]) -> None:
        bounded = set(LOCAL_FEATURES) - {"tempo", "loudness"}
        for name, features in computed.items():
            assert set(features) == set(LOCAL_FEATURES), name
            for key in bounded:
                assert 0.0 <= features[key] <= 1.0, f"{name}.{key}={features[key]}"
            assert features["tempo"] >= 0.0, name
            assert -60.0 <= features["loudness"] <= 0.0, name
            assert all(np.isfinite(v) for v in features.values()), name

    def test_deterministic_given_same_audio(self, wavs: dict[str, Path]) -> None:
        first = compute_features(wavs["clicks"])
        second = compute_features(wavs["clicks"])
        assert first == second

    def test_click_train_tracks_a_tempo(self, computed: dict[str, dict[str, float]]) -> None:
        # 120 bpm grid; allow the usual half/double ambiguity, not silence.
        assert 55.0 <= computed["clicks"]["tempo"] <= 250.0

    def test_click_train_more_danceable_than_pure_tone(
        self, computed: dict[str, dict[str, float]]
    ) -> None:
        assert computed["clicks"]["danceability"] > computed["sine"]["danceability"]
        assert computed["clicks"]["danceability"] > 0.4

    def test_noise_less_acoustic_than_pure_tone(
        self, computed: dict[str, dict[str, float]]
    ) -> None:
        assert computed["noise"]["acousticness"] < computed["sine"]["acousticness"]

    def test_energy_and_loudness_track_amplitude(
        self, computed: dict[str, dict[str, float]]
    ) -> None:
        assert computed["noise"]["energy"] > computed["quiet_noise"]["energy"]
        assert computed["noise"]["loudness"] > computed["quiet_noise"]["loudness"]

    def test_noise_more_speechy_than_pure_tone(self, computed: dict[str, dict[str, float]]) -> None:
        # White noise has speech-like zero-crossing density; a tone does not.
        assert computed["noise"]["speechiness"] > computed["sine"]["speechiness"]

    def test_pure_tone_reads_instrumental(self, computed: dict[str, dict[str, float]]) -> None:
        assert computed["sine"]["instrumentalness"] > 0.5

    def test_silence_is_quiet_not_nan(self, computed: dict[str, dict[str, float]]) -> None:
        assert computed["silence"]["loudness"] == pytest.approx(-60.0)
        assert computed["silence"]["energy"] < 0.1


class TestPreviewCache:
    def test_round_trip(self, tmp_path: Path) -> None:
        cache = PreviewCache(tmp_path / "cache", max_bytes=10_000)
        assert cache.get("http://x/1.mp3") is None
        path = cache.put("http://x/1.mp3", b"abc")
        assert cache.get("http://x/1.mp3") == path
        assert path.read_bytes() == b"abc"

    def test_evicts_oldest_when_over_cap(self, tmp_path: Path) -> None:
        import os

        cache = PreviewCache(tmp_path / "cache", max_bytes=250)
        first = cache.put("http://x/1", b"a" * 100)
        second = cache.put("http://x/2", b"b" * 100)
        # Force a strict mtime order so eviction age is unambiguous.
        os.utime(first, (1_000, 1_000))
        os.utime(second, (2_000, 2_000))
        third = cache.put("http://x/3", b"c" * 100)

        assert cache.get("http://x/1") is None  # oldest evicted
        assert cache.get("http://x/2") is not None
        assert third.exists()
        total = sum(p.stat().st_size for p in (tmp_path / "cache").iterdir())
        assert total <= 250


class FakePreviewSearch:
    def __init__(self, previews: dict[str, str]) -> None:
        self.previews = previews  # "title|artist" -> url
        self.calls: list[tuple[str, str]] = []

    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None:
        self.calls.append((title, artist))
        url = self.previews.get(f"{title.lower()}|{artist.lower()}")
        if url is None:
            return None
        return DeezerTrack(id=1, title=title, preview=url, artist_name=artist)


class TestLocalDspClient:
    async def test_analyze_downloads_caches_and_computes(self, tmp_path: Path) -> None:
        audio = tmp_path / "src.wav"
        write_wav(audio, sine(1.0))
        payload = audio.read_bytes()
        hits: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(str(request.url))
            return httpx.Response(200, content=payload)

        client = LocalDspClient(
            previews=FakePreviewSearch({"tone|artist": "https://cdn.example/tone"}),
            cache=PreviewCache(tmp_path / "cache", max_bytes=10_000_000),
            transport=httpx.MockTransport(handler),
        )
        try:
            first = await client.analyze("Tone", "Artist")
            second = await client.analyze("Tone", "Artist")
        finally:
            await client.aclose()

        assert first is not None and second is not None
        assert set(first.features) == set(LOCAL_FEATURES)
        assert first.features == second.features
        assert first.preview_url == "https://cdn.example/tone"
        assert hits == ["https://cdn.example/tone"]  # second run hit the disk cache

    async def test_analyze_returns_none_without_preview(self, tmp_path: Path) -> None:
        client = LocalDspClient(
            previews=FakePreviewSearch({}),
            cache=PreviewCache(tmp_path / "cache", max_bytes=10_000),
            transport=httpx.MockTransport(lambda _: httpx.Response(404)),
        )
        try:
            assert await client.analyze("Ghost", "Nobody") is None
        finally:
            await client.aclose()

    async def test_audio_fetches_are_concurrency_capped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inflight = 0
        max_inflight = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal inflight, max_inflight
            inflight += 1
            max_inflight = max(max_inflight, inflight)
            await asyncio.sleep(0.01)
            inflight -= 1
            return httpx.Response(200, content=b"bytes")

        monkeypatch.setattr(
            localdsp, "compute_features", lambda _path: dict.fromkeys(LOCAL_FEATURES, 0.5)
        )

        previews = FakePreviewSearch({f"t{i}|a": f"https://cdn.example/{i}" for i in range(5)})
        client = LocalDspClient(
            previews=previews,
            cache=PreviewCache(tmp_path / "cache", max_bytes=10_000_000),
            transport=httpx.MockTransport(handler),
            max_concurrent_fetches=2,
        )
        try:
            results = await asyncio.gather(*(client.analyze(f"t{i}", "a") for i in range(5)))
        finally:
            await client.aclose()

        assert all(r is not None for r in results)
        assert max_inflight <= 2
