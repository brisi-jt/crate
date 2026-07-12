"""Pure insight metrics over plain structures.

Every function here is a hand-computable transform of dicts / lists / numpy
arrays - no ORM, no session. The engine loads the library once and feeds these.
All feature inputs are library percentiles (0..1), never raw Essentia values;
key/mode go through the shared Camelot helper.

The nine calibrated features are the ranking population for fingerprints,
ridgelines, mood, GS-score, and adds-over-time centroids. Genre metrics use
ENAO membership weights; era metrics use parsed release years.
"""

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from crate.services.analytics.flow import camelot

# The nine features whose percentiles define acoustic identity. Ordered for a
# stable fingerprint / ridgeline layout.
FINGERPRINT_FEATURES = (
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "tempo",
    "loudness",
)

# Mood grid resolution (energy x valence): a 6x6 density field.
MOOD_GRID_SIZE = 6
# Tempo histogram: fixed BPM bands so the ruler reads the same across libraries.
TEMPO_BIN_WIDTH = 10
TEMPO_MIN = 60
TEMPO_MAX = 200
# Ridgeline resolution: percentile buckets per feature.
RIDGELINE_BUCKETS = 20
# Coming-of-age band from the taste-freeze literature.
COMING_OF_AGE_START = 16
COMING_OF_AGE_END = 24


# ------------------------------------------------------------ taste identity


def acoustic_fingerprint(vectors: list[dict[str, float]]) -> list[dict[str, Any]]:
    """Mean percentile per feature - the library's average sound.

    Empty library returns an empty list; the caller renders the pending state.
    """
    if not vectors:
        return []
    return [
        {
            "feature": feature,
            "percentile": round(
                sum(vector.get(feature, 0.5) for vector in vectors) / len(vectors), 4
            ),
        }
        for feature in FINGERPRINT_FEATURES
    ]


def shannon_entropy(weights: dict[str, float]) -> float:
    """Shannon entropy H = -Σ pᵢ log₂ pᵢ over a weight distribution (bits).

    Weights are normalized to shares first; zero/negative weights are ignored.
    A single category gives 0 (no uncertainty).
    """
    positive = {key: w for key, w in weights.items() if w > 0}
    total = sum(positive.values())
    if total <= 0:
        return 0.0
    entropy = 0.0
    for weight in positive.values():
        share = weight / total
        entropy -= share * math.log2(share)
    return entropy


def effective_count(entropy: float) -> float:
    """2^H - the effective number of equally-weighted categories."""
    return 2.0**entropy


def gs_score(vectors: list[dict[str, float]]) -> float | None:
    """Generalist-specialist acoustic sprawl: mean distance from the centroid.

    Computed in the unit-cube percentile space and normalized by the cube
    diagonal sqrtd so it lands in [0, 1]; higher = more sprawl (generalist).
    Needs at least two enriched tracks.
    """
    if len(vectors) < 2:
        return None
    features = FINGERPRINT_FEATURES
    matrix = np.array([[vector.get(f, 0.5) for f in features] for vector in vectors], dtype=float)
    centroid = matrix.mean(axis=0)
    distances = np.linalg.norm(matrix - centroid, axis=1)
    diagonal = math.sqrt(len(features))
    return float(distances.mean() / diagonal)


@dataclass(frozen=True)
class Typology:
    archetype: str
    genre_breadth: float  # effective genre count, normalized 0..1
    acoustic_sprawl: float  # GS-score 0..1
    rarity: float  # mean genre rarity 0..1 (1 = niche)


def omnivore_typology(effective_genres: float, sprawl: float | None, rarity: float) -> Typology:
    """One archetype from breadth x sprawl x rarity.

    - omnivore: broad genres and high acoustic sprawl.
    - specialist: narrow genres and low sprawl.
    - snobivore: narrow/deep but rare (niche depth over breadth).
    - explorer: the remaining broad-but-not-rare / mixed middle.

    Thresholds are on interpretable, library-independent scales (effective
    genre count, normalized sprawl, rarity share), documented inline.
    """
    sprawl_value = sprawl if sprawl is not None else 0.0
    # Effective genres normalized against a soft ceiling of 12 distinct genres.
    breadth = min(1.0, effective_genres / 12.0)
    broad = breadth >= 0.5
    sprawly = sprawl_value >= 0.35
    niche = rarity >= 0.6

    if broad and sprawly:
        archetype = "omnivore"
    elif not broad and niche:
        archetype = "snobivore"
    elif not broad and not sprawly:
        archetype = "specialist"
    else:
        archetype = "explorer"
    return Typology(
        archetype=archetype,
        genre_breadth=round(breadth, 4),
        acoustic_sprawl=round(sprawl_value, 4),
        rarity=round(rarity, 4),
    )


# ------------------------------------------------------------------ genres


def genre_shares(genre_weights: dict[str, float], *, top: int = 12) -> list[dict[str, Any]]:
    """Top genres by library share, each with its normalized share.

    genre_weights maps genre name -> summed library weight. Shares normalize
    over the whole distribution (not just the top slice), so they read as
    "share of your library" honestly.
    """
    total = sum(w for w in genre_weights.values() if w > 0)
    if total <= 0:
        return []
    ranked = sorted(genre_weights.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"genre": name, "share": round(weight / total, 4)}
        for name, weight in ranked[:top]
        if weight > 0
    ]


def genre_rarity(
    genre_weights: dict[str, float],
    enao_ranks: dict[str, int | None],
    *,
    rank_ceiling: int = 1496,
    top: int = 12,
) -> tuple[float, list[dict[str, Any]]]:
    """Mean library-weighted genre rarity plus the rarest genres.

    Rarity of a genre = enao_rank / rank_ceiling (1 = the most niche end of the
    ENAO atlas). The library score is the weight-weighted mean rarity over
    genres with a known rank. Returns (mean_rarity, rarest[]).
    """
    weighted_sum = 0.0
    weight_total = 0.0
    entries: list[dict[str, Any]] = []
    for genre, weight in genre_weights.items():
        rank = enao_ranks.get(genre)
        if rank is None or weight <= 0:
            continue
        rarity = min(1.0, rank / rank_ceiling)
        weighted_sum += rarity * weight
        weight_total += weight
        entries.append({"genre": genre, "enao_rank": rank, "rarity": round(rarity, 4)})
    mean_rarity = round(weighted_sum / weight_total, 4) if weight_total > 0 else 0.0
    entries.sort(key=lambda entry: (-entry["rarity"], entry["genre"]))
    return mean_rarity, entries[:top]


# -------------------------------------------------------- collection archaeology


def monthly_adds(
    adds: list[tuple[str, dict[str, float] | None]],
) -> list[dict[str, Any]]:
    """Adds bucketed by YYYY-MM with a per-bucket acoustic centroid.

    adds is a list of (month_key "YYYY-MM", centroid dict or None). The
    centroid averages the three color features of enriched adds in that month;
    a month with no enriched adds gets a null centroid but still counts.
    Sorted oldest first - the geological core sample.
    """
    counts: Counter[str] = Counter()
    sums: dict[str, dict[str, float]] = {}
    enriched: Counter[str] = Counter()
    for month, centroid in adds:
        counts[month] += 1
        if centroid is not None:
            enriched[month] += 1
            accumulator = sums.setdefault(
                month, {"acousticness": 0.0, "energy": 0.0, "valence": 0.0}
            )
            for key in accumulator:
                accumulator[key] += centroid.get(key, 0.5)
    result = []
    for month in sorted(counts):
        n = enriched[month]
        centroid = {key: round(value / n, 4) for key, value in sums[month].items()} if n else None
        result.append({"month": month, "count": counts[month], "centroid": centroid})
    return result


def abandoned_playlists(
    last_activity: dict[int, tuple[str, object]],
    *,
    dormant_months: int = 6,
) -> list[dict[str, Any]]:
    """Playlists whose last add/remove is older than dormant_months.

    last_activity maps playlist_id -> (name, months_since_activity as int); the
    caller pre-computes the month gap. Returns the dormant playlists, dustiest
    first.
    """
    entries = [
        {"playlist_id": pid, "name": name, "months_dormant": months}
        for pid, (name, months) in last_activity.items()
        if isinstance(months, int) and months >= dormant_months
    ]
    entries.sort(key=lambda entry: (-entry["months_dormant"], entry["name"]))
    return entries


# ------------------------------------------------------------ sonic signatures


def camelot_distribution(
    audio: list[tuple[int | None, int | None, float | None]],
) -> list[dict[str, Any]]:
    """Track counts per Camelot code, tinted by mean valence percentile.

    audio is a list of (key, mode, valence_percentile). Tracks whose key/mode
    don't map to a Camelot position are dropped. Returns every occupied code,
    sorted by wheel number then ring, so empty codes are visibly absent.
    """
    buckets: dict[str, list[float | None]] = {}
    numbers: dict[str, tuple[int, str]] = {}
    for key, mode, valence in audio:
        position = camelot(key, mode)
        if position is None:
            continue
        number, ring = position
        code = f"{number}{ring}"
        buckets.setdefault(code, []).append(valence)
        numbers[code] = (number, ring)

    result = []
    for code, valences in buckets.items():
        present = [v for v in valences if v is not None]
        mean_valence = round(sum(present) / len(present), 4) if present else None
        number, ring = numbers[code]
        result.append(
            {
                "code": code,
                "number": number,
                "ring": ring,
                "count": len(valences),
                "mean_valence": mean_valence,
            }
        )
    result.sort(key=lambda entry: (entry["number"], entry["ring"]))
    return result


def mood_grid(pairs: list[tuple[float, float]], size: int = MOOD_GRID_SIZE) -> dict[str, Any]:
    """Energy x valence density grid plus the four quadrant shares.

    pairs are (energy_percentile, valence_percentile). The grid is size x size
    counts (row = valence band bottom→top, col = energy band left→right);
    quadrants split at the 0.5 midpoint.
    """
    grid = [[0 for _ in range(size)] for _ in range(size)]
    quadrants = {"calm_sad": 0, "energetic_tense": 0, "peaceful_content": 0, "happy_energetic": 0}
    for energy, valence in pairs:
        col = min(size - 1, int(energy * size))
        row = min(size - 1, int(valence * size))
        grid[row][col] += 1
        high_energy = energy >= 0.5
        high_valence = valence >= 0.5
        if high_energy and high_valence:
            quadrants["happy_energetic"] += 1
        elif high_energy and not high_valence:
            quadrants["energetic_tense"] += 1
        elif not high_energy and high_valence:
            quadrants["peaceful_content"] += 1
        else:
            quadrants["calm_sad"] += 1
    total = len(pairs)
    shares = {key: round(count / total, 4) if total else 0.0 for key, count in quadrants.items()}
    return {"grid": grid, "size": size, "counts": quadrants, "shares": shares, "total": total}


def tempo_histogram(
    tempos: list[float | None],
    *,
    bin_width: int = TEMPO_BIN_WIDTH,
    low: int = TEMPO_MIN,
    high: int = TEMPO_MAX,
) -> list[dict[str, int]]:
    """BPM band counts over fixed [low, high) bands of bin_width.

    Raw tempo (not percentile) - the BPM ruler is an absolute, tangible scale.
    Tempos outside [low, high) clamp into the edge bands; None is skipped.
    """
    bands = list(range(low, high, bin_width))
    counts = dict.fromkeys(bands, 0)
    for tempo in tempos:
        if tempo is None or tempo <= 0:
            continue
        clamped = max(low, min(high - 1, tempo))
        band = low + int((clamped - low) // bin_width) * bin_width
        counts[band] += 1
    return [
        {"bpm_low": band, "bpm_high": band + bin_width, "count": counts[band]} for band in bands
    ]


def feature_ridgelines(
    vectors: list[dict[str, float]], *, buckets: int = RIDGELINE_BUCKETS
) -> list[dict[str, Any]]:
    """Per-feature percentile-bucketed distribution (the ridgeline shapes).

    For each of the nine features, counts how many tracks fall in each of
    `buckets` equal percentile slices. Catches bimodality a mean would hide.
    """
    ridgelines = []
    for feature in FINGERPRINT_FEATURES:
        histogram = [0 for _ in range(buckets)]
        for vector in vectors:
            value = vector.get(feature, 0.5)
            index = min(buckets - 1, int(value * buckets))
            histogram[index] += 1
        ridgelines.append({"feature": feature, "buckets": histogram})
    return ridgelines


# ------------------------------------------------------------------- oddities


@dataclass(frozen=True)
class Superlative:
    label: str
    track_id: int
    name: str
    artist: str
    value: float


def extremes_board(
    tracks: list[dict[str, Any]],
    vectors: dict[int, dict[str, float]],
) -> list[dict[str, Any]]:
    """Longest/shortest track and the most-X track per feature.

    tracks carry {"track_id", "name", "artist", "duration_ms"}. Duration
    superlatives use duration_ms; feature superlatives argmax the percentile
    vectors. Each entry is a click-to-play readout.
    """
    board: list[dict[str, Any]] = []

    def _meta(track_id: int) -> dict[str, Any]:
        for track in tracks:
            if track["track_id"] == track_id:
                return track
        return {"name": "", "artist": ""}

    durations = [(t["track_id"], t["duration_ms"]) for t in tracks if t.get("duration_ms")]
    if durations:
        longest = max(durations, key=lambda item: item[1])
        shortest = min(durations, key=lambda item: item[1])
        for label, (track_id, ms) in (("longest", longest), ("shortest", shortest)):
            meta = _meta(track_id)
            board.append(
                {
                    "label": label,
                    "track_id": track_id,
                    "name": meta["name"],
                    "artist": meta["artist"],
                    "value": round(ms / 1000.0, 1),
                    "unit": "seconds",
                }
            )

    for feature in FINGERPRINT_FEATURES:
        present = [(tid, vec[feature]) for tid, vec in vectors.items() if feature in vec]
        if not present:
            continue
        top_id, top_value = max(present, key=lambda item: (item[1], -item[0]))
        meta = _meta(top_id)
        board.append(
            {
                "label": f"most_{feature}",
                "track_id": top_id,
                "name": meta["name"],
                "artist": meta["artist"],
                "value": round(top_value, 4),
                "unit": "percentile",
            }
        )
    return board


# --------------------------------------------------------------------- eras


def era_profile(
    years: list[int],
    *,
    birth_year: int | None = None,
) -> dict[str, Any]:
    """Decade distribution + center-of-gravity year + taste-freeze reading.

    years are per-track release years. Returns decade counts, the modal and
    median year, and - only when birth_year is set - the share of the library
    released during the user's 16-24 coming-of-age band.
    """
    if not years:
        return {
            "decades": [],
            "center_of_gravity": None,
            "median_year": None,
            "coming_of_age": None,
            "total": 0,
        }
    decade_counts: Counter[int] = Counter((year // 10) * 10 for year in years)
    decades = [
        {"decade": decade, "count": count} for decade, count in sorted(decade_counts.items())
    ]
    modal_year = Counter(years).most_common(1)[0][0]
    ordered = sorted(years)
    median_year = ordered[len(ordered) // 2]

    coming_of_age = None
    if birth_year is not None:
        band_start = birth_year + COMING_OF_AGE_START
        band_end = birth_year + COMING_OF_AGE_END
        in_band = sum(1 for year in years if band_start <= year <= band_end)
        coming_of_age = {
            "band_start_year": band_start,
            "band_end_year": band_end,
            "share": round(in_band / len(years), 4),
            "count": in_band,
        }
    return {
        "decades": decades,
        "center_of_gravity": modal_year,
        "median_year": median_year,
        "coming_of_age": coming_of_age,
        "total": len(years),
    }
