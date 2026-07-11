"""Local audio analysis: compute audio features from 30-second Deezer previews.

The last rung of the enrichment ladder before "missing". When neither
ReccoBeats nor FreqBlog knows a track, its Deezer preview is downloaded and
nine features are computed here with librosa. Raw local values live in a
distribution of their own, so they are quantile-mapped into the ReccoBeats
space before storage (see the calibration section below); the raw values are
kept alongside in ``track_features.local_raw``.

Everything here is deterministic: the same audio bytes always produce the
same feature values (librosa is pure numpy given fixed inputs).

Feature formulas and their limitations
--------------------------------------

All 0..1 features are clamped. ``tempo`` is BPM and ``loudness`` is dB —
both quantile-mapped like the rest, so their unit never leaks downstream.

tempo
    ``librosa.beat.beat_track`` BPM estimate. Solid for percussive material;
    subject to the usual half/double-tempo ambiguity on sparse or rubato
    audio. 0.0 when no beat is found.
energy
    ``0.5 * rms_norm + 0.5 * flux_norm`` where ``rms_norm`` maps mean RMS
    dBFS from [-60, 0] onto [0, 1] and ``flux_norm`` is mean onset strength
    scaled by ``FLUX_REFERENCE``. A loudness-plus-activity proxy: it tracks
    perceptual intensity reasonably but under-rates quiet-but-dense material.
danceability
    ``0.7 * regularity + 0.3 * pulse``. ``regularity`` is
    ``1 - cv(inter-beat intervals)`` (coefficient of variation of the beat
    grid — a steady grid scores high); ``pulse`` is mean onset strength at
    the tracked beats scaled by ``PULSE_REFERENCE``. 0.0 with fewer than
    four tracked beats. Rhythm-regularity proxy only — it knows nothing
    about groove, syncopation, or genre.
valence
    ``0.5 * major_score + 0.5 * brightness``. ``major_score`` correlates the
    mean chroma vector against all 24 rotations of the Krumhansl-Schmuckler
    major/minor key profiles and maps (best major - best minor) onto [0, 1];
    ``brightness`` maps mean spectral centroid from [500, 4000] Hz onto
    [0, 1]. WEAK — documented as such deliberately: musical positivity is
    not recoverable from mode plus brightness; treat this as a coarse
    dark-vs-bright axis, never as emotion ground truth.
acousticness
    ``1 - (0.6 * flatness_scaled + 0.4 * rolloff_norm)``. Spectral flatness
    (noise-likeness, scaled by ``FLATNESS_REFERENCE``) and spectral rolloff
    (share of energy pushed into high frequencies) both indicate produced /
    electronic signal. A proxy: heavily-distorted acoustic recordings score
    low, sparse synth pads score high.
instrumentalness
    ``1 - clamp(mid-MFCC temporal variance / MFCC_VARIANCE_REFERENCE)``.
    Vocals modulate the mid cepstral coefficients (2..13) over time, so low
    variance suggests no voice. Weak vocal detector — expressive lead
    instruments read as "vocal" and static rap beds can read as
    "instrumental".
speechiness
    ``0.5 * zcr_norm + 0.5 * syllabic``. Zero-crossing rate (fricatives)
    scaled by ``ZCR_REFERENCE``, plus the share of the RMS-envelope
    modulation spectrum in the syllabic 2-8 Hz band. Weak: melodic rap and
    spoken-word-with-music sit in the middle of the scale.
liveness
    Mean spectral flatness of the quietest ``QUIET_FRAME_SHARE`` of frames,
    scaled by ``QUIET_FLATNESS_REFERENCE`` — crowd noise and room reverb keep
    the "silence" between hits noisy. VERY weak; studio tracks with heavy
    reverb tails also score high.
loudness
    ``20·log10(rms)`` clipped to [-60, 0] dBFS. An integrated RMS proxy for
    LUFS: no K-weighting, no gating, so it reads a few dB off a true
    ITU-R BS.1770 measurement but orders tracks the same way.

Calibration (local → ReccoBeats space)
--------------------------------------

Local values are NOT comparable to ReccoBeats values feature-for-feature —
the distributions differ. ``FeatureCalibration`` percentiles pool all
``present`` rows into one space, so raw local values would pollute it.
Instead a per-feature quantile map is fitted on the overlap set: tracks that
already have ReccoBeats features AND a resolvable preview are analyzed
locally, giving matched (local, reccobeats) samples per feature. Both sides'
quantile grids become the anchors of a monotone piecewise-linear map; every
locally-analyzed track stores the mapped value in the feature columns
(``source = essentia``) and the raw value in ``local_raw``. Below
``MIN_OVERLAP_SAMPLES`` matched samples no map is fitted and raw values are
stored unmapped (flagged on the enrichment report as uncalibrated).
"""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from crate.services.enrichment.models import DeezerTrack

# The nine locally-computed features. key and mode are not derived — they
# stay null on essentia-sourced rows.
LOCAL_FEATURES = (
    "tempo",
    "energy",
    "danceability",
    "valence",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "liveness",
    "loudness",
)

# Analysis sample rate; previews are resampled to mono at this rate.
ANALYSIS_SAMPLE_RATE = 22050
# Onset-strength value treated as "full" activity for the energy flux term.
FLUX_REFERENCE = 10.0
# Onset strength at beats treated as a "full" pulse for danceability.
PULSE_REFERENCE = 5.0
# Spectral flatness treated as "fully noise-like" (musical signals sit well
# below the theoretical 1.0).
FLATNESS_REFERENCE = 0.1
# Mid-MFCC temporal standard deviation treated as "fully vocal".
MFCC_VARIANCE_REFERENCE = 50.0
# Zero-crossing rate treated as "fully speech-like".
ZCR_REFERENCE = 0.15
# Share of quietest frames inspected for the liveness noise floor.
QUIET_FRAME_SHARE = 0.2
# Quiet-frame flatness treated as a "fully live" noise floor.
QUIET_FLATNESS_REFERENCE = 0.2

# Krumhansl-Schmuckler key profiles (major / minor), C-rooted.
KRUMHANSL_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KRUMHANSL_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

# Quantile-map grid: 11 anchors (deciles plus both extremes).
QUANTILE_GRID_SIZE = 11
# Fewest matched (local, reccobeats) samples worth fitting a map from.
MIN_OVERLAP_SAMPLES = 8
# Most overlap tracks analyzed when fitting — bounds first-fit preview cost.
OVERLAP_SAMPLE_LIMIT = 24

# Concurrent preview downloads (the Deezer search itself is rate-limited
# separately by the client's limiter).
MAX_CONCURRENT_FETCHES = 2

# Enrichment passes can walk a lot of tracks in one go, so their Deezer
# searches run gentler than the interactive discovery client: one per second.
DEEZER_PREVIEW_MIN_INTERVAL = 1.0


def default_cache_dir() -> Path:
    """Preview cache location when settings leave it unset."""
    import tempfile

    return Path(tempfile.gettempdir()) / "crate-previews"


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def compute_features(path: Path) -> dict[str, float]:
    """The nine local features for one audio file (see module docstring).

    Deterministic: the same file always yields the same values.
    """
    # librosa (and its numba/scipy tree) is heavy — imported only when a
    # preview is actually analyzed, never at app boot.
    import librosa
    import numpy as np

    y, sr = librosa.load(str(path), sr=ANALYSIS_SAMPLE_RATE, mono=True)
    if y.size == 0:
        y = np.zeros(ANALYSIS_SAMPLE_RATE, dtype=np.float32)

    eps = 1e-10
    rms_frames = librosa.feature.rms(y=y)[0]
    rms = float(np.sqrt(np.mean(np.square(y))))
    loudness = float(np.clip(20.0 * np.log10(rms + eps), -60.0, 0.0))

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    rms_norm = (loudness + 60.0) / 60.0
    flux_norm = _clamp01(float(np.mean(onset_env)) / FLUX_REFERENCE)
    energy = _clamp01(0.5 * rms_norm + 0.5 * flux_norm)

    tempo_raw, beat_frames = librosa.beat.beat_track(y=y, sr=sr, onset_envelope=onset_env)
    tempo = float(np.atleast_1d(tempo_raw)[0])

    if len(beat_frames) >= 4:
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        intervals = np.diff(beat_times)
        cv = float(np.std(intervals) / (np.mean(intervals) + eps))
        regularity = _clamp01(1.0 - cv)
        pulse = _clamp01(float(np.mean(onset_env[beat_frames])) / PULSE_REFERENCE)
        danceability = _clamp01(0.7 * regularity + 0.3 * pulse)
    else:
        danceability = 0.0

    flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)[0]))
    rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)[0]))
    flatness_scaled = _clamp01(flatness / FLATNESS_REFERENCE)
    rolloff_norm = _clamp01(rolloff / (sr / 2.0))
    acousticness = _clamp01(1.0 - (0.6 * flatness_scaled + 0.4 * rolloff_norm))

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mid_mfcc_var = float(np.mean(np.std(mfcc[1:], axis=1)))
    instrumentalness = _clamp01(1.0 - mid_mfcc_var / MFCC_VARIANCE_REFERENCE)

    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)[0]))
    zcr_norm = _clamp01(zcr / ZCR_REFERENCE)
    syllabic = _syllabic_modulation_share(rms_frames, sr)
    speechiness = _clamp01(0.5 * zcr_norm + 0.5 * syllabic)

    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    valence_mode = _major_score(np.mean(chroma, axis=1))
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)[0]))
    brightness = _clamp01((centroid - 500.0) / (4000.0 - 500.0))
    valence = _clamp01(0.5 * valence_mode + 0.5 * brightness)

    liveness = _quiet_floor_flatness(y, rms_frames)

    return {
        "tempo": tempo,
        "energy": energy,
        "danceability": danceability,
        "valence": valence,
        "acousticness": acousticness,
        "instrumentalness": instrumentalness,
        "speechiness": speechiness,
        "liveness": liveness,
        "loudness": loudness,
    }


def _syllabic_modulation_share(rms_frames, sr: int) -> float:
    """Share of RMS-envelope modulation energy in the syllabic 2-8 Hz band."""
    import numpy as np

    if rms_frames.size < 8:
        return 0.0
    envelope = rms_frames - np.mean(rms_frames)
    spectrum = np.abs(np.fft.rfft(envelope))
    # librosa's default hop is 512 samples, so envelope frames tick at sr/512.
    frame_rate = sr / 512.0
    freqs = np.fft.rfftfreq(envelope.size, d=1.0 / frame_rate)
    total = float(np.sum(spectrum[(freqs > 0.5) & (freqs <= 20.0)]))
    if total <= 0.0:
        return 0.0
    syllabic = float(np.sum(spectrum[(freqs >= 2.0) & (freqs <= 8.0)]))
    return _clamp01(syllabic / total)


def _major_score(mean_chroma) -> float:
    """Best-major minus best-minor Krumhansl correlation, mapped onto [0, 1]."""
    import numpy as np

    if float(np.std(mean_chroma)) < 1e-8:
        return 0.5  # tonally featureless — sit on the fence
    best_major = max(
        _profile_correlation(mean_chroma, np.roll(KRUMHANSL_MAJOR, k)) for k in range(12)
    )
    best_minor = max(
        _profile_correlation(mean_chroma, np.roll(KRUMHANSL_MINOR, k)) for k in range(12)
    )
    return _clamp01((best_major - best_minor) * 2.0 + 0.5)


def _profile_correlation(chroma, profile) -> float:
    import numpy as np

    if float(np.std(profile)) < 1e-8:
        return 0.0
    return float(np.corrcoef(chroma, profile)[0, 1])


def _quiet_floor_flatness(y, rms_frames) -> float:
    """Flatness of the quietest frames — the liveness noise-floor proxy."""
    import librosa
    import numpy as np

    if rms_frames.size == 0:
        return 0.0
    flatness_frames = librosa.feature.spectral_flatness(y=y)[0]
    n = max(1, int(rms_frames.size * QUIET_FRAME_SHARE))
    frames = min(rms_frames.size, flatness_frames.size)
    quietest = np.argsort(rms_frames[:frames])[:n]
    return _clamp01(float(np.mean(flatness_frames[quietest])) / QUIET_FLATNESS_REFERENCE)


# ---------------------------------------------------------------- calibration


def quantile_grid(values: list[float], size: int = QUANTILE_GRID_SIZE) -> list[float]:
    """``size`` linearly-interpolated quantiles from min to max, ascending."""
    import numpy as np

    if not values:
        raise ValueError("quantile_grid needs at least one value")
    qs = np.linspace(0.0, 1.0, size)
    return [float(v) for v in np.quantile(np.asarray(values, dtype=float), qs)]


def fit_quantile_map(
    local_values: list[float], target_values: list[float]
) -> tuple[list[float], list[float]]:
    """Matched anchor grids mapping the local distribution onto the target's."""
    if len(local_values) != len(target_values):
        raise ValueError("quantile map needs matched samples")
    return quantile_grid(local_values), quantile_grid(target_values)


def apply_quantile_map(
    local_anchors: list[float], target_anchors: list[float], value: float
) -> float:
    """Piecewise-linear interpolation; values beyond the anchors clamp to the ends."""
    import numpy as np

    return float(np.interp(value, local_anchors, target_anchors))


# --------------------------------------------------------------- audio cache


class PreviewCache:
    """Disk cache for downloaded preview audio, capped by total size.

    Files are named by URL hash. When the cap is exceeded the oldest files
    (by modification time) are evicted until the cache fits again.
    """

    def __init__(self, directory: Path, *, max_bytes: int) -> None:
        self._dir = directory
        self._max_bytes = max_bytes
        self._dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, url: str) -> Path:
        return self._dir / (hashlib.sha256(url.encode()).hexdigest() + ".audio")

    def get(self, url: str) -> Path | None:
        path = self.path_for(url)
        return path if path.exists() else None

    def put(self, url: str, data: bytes) -> Path:
        path = self.path_for(url)
        path.write_bytes(data)
        self._evict()
        return path

    def _evict(self) -> None:
        files = sorted(
            (p for p in self._dir.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= self._max_bytes:
                break
            total -= path.stat().st_size
            path.unlink()


# --------------------------------------------------------------------- client


@dataclass
class LocalAnalysis:
    """One locally-analyzed preview: raw feature values plus provenance."""

    features: dict[str, float]
    preview_url: str


class PreviewSearch(Protocol):
    """Structural stand-in for DeezerClient.search_preview (typing only)."""

    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None: ...


class LocalDspClient:
    """Preview lookup + download + feature computation for one track.

    The Deezer search is paced by the injected client's own limiter; audio
    downloads run through a small concurrency cap so a batch never hammers
    the CDN. DSP work runs in a thread so the event loop stays responsive.
    """

    def __init__(
        self,
        *,
        previews: "PreviewSearch",
        cache: PreviewCache,
        transport: httpx.BaseTransport | None = None,
        max_concurrent_fetches: int = MAX_CONCURRENT_FETCHES,
    ) -> None:
        self._previews = previews
        self._cache = cache
        self._http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30.0))
        self._fetch_slots = asyncio.Semaphore(max_concurrent_fetches)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def analyze(self, title: str, artist: str) -> LocalAnalysis | None:
        """Raw local features for a track, or None when no preview exists."""
        result = await self._previews.search_preview(title, artist)
        if result is None or not result.preview:
            return None
        path = self._cache.get(result.preview)
        if path is None:
            async with self._fetch_slots:
                response = await self._http.get(result.preview)
            response.raise_for_status()
            path = self._cache.put(result.preview, response.content)
        features = await asyncio.to_thread(compute_features, path)
        return LocalAnalysis(features=features, preview_url=result.preview)
