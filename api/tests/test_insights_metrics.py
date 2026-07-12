"""Hand-computed micro-fixtures for every insight metric.

Each assertion is derived from the formula, not from the code's output — the
tests are the specification.
"""

import math

import pytest

from crate.services.insights import metrics

pytestmark = pytest.mark.unit


# ------------------------------------------------------------ taste identity


def test_acoustic_fingerprint_means_each_feature() -> None:
    vectors = [
        dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.2),
        dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.4),
    ]
    fp = metrics.acoustic_fingerprint(vectors)
    assert len(fp) == 9
    # mean of 0.2 and 0.4 = 0.3 for every feature
    assert all(entry["percentile"] == 0.3 for entry in fp)
    assert [entry["feature"] for entry in fp] == list(metrics.FINGERPRINT_FEATURES)


def test_acoustic_fingerprint_empty() -> None:
    assert metrics.acoustic_fingerprint([]) == []


def test_shannon_entropy_uniform_two_categories_is_one_bit() -> None:
    # two equal categories: H = -(0.5 log2 0.5) * 2 = 1.0
    assert metrics.shannon_entropy({"a": 1.0, "b": 1.0}) == pytest.approx(1.0)


def test_shannon_entropy_single_category_is_zero() -> None:
    assert metrics.shannon_entropy({"a": 5.0}) == 0.0


def test_shannon_entropy_four_equal_is_two_bits() -> None:
    assert metrics.shannon_entropy(dict.fromkeys("abcd", 1.0)) == pytest.approx(2.0)


def test_effective_count_is_two_to_the_h() -> None:
    assert metrics.effective_count(2.0) == pytest.approx(4.0)
    assert metrics.effective_count(0.0) == pytest.approx(1.0)


def test_gs_score_identical_tracks_is_zero() -> None:
    vectors = [dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.5)] * 3
    assert metrics.gs_score(vectors) == pytest.approx(0.0)


def test_gs_score_one_track_is_none() -> None:
    assert metrics.gs_score([dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.5)]) is None


def test_gs_score_two_opposite_corners() -> None:
    # two points at all-0 and all-1: centroid all-0.5, each at distance
    # sqrt(9 * 0.25) = 1.5; mean = 1.5; normalized by diagonal sqrt(9)=3 → 0.5
    vectors = [
        dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.0),
        dict.fromkeys(metrics.FINGERPRINT_FEATURES, 1.0),
    ]
    assert metrics.gs_score(vectors) == pytest.approx(0.5)


def test_typology_omnivore() -> None:
    t = metrics.omnivore_typology(effective_genres=8.0, sprawl=0.5, rarity=0.3)
    assert t.archetype == "omnivore"


def test_typology_specialist() -> None:
    t = metrics.omnivore_typology(effective_genres=2.0, sprawl=0.1, rarity=0.2)
    assert t.archetype == "specialist"


def test_typology_snobivore() -> None:
    t = metrics.omnivore_typology(effective_genres=2.0, sprawl=0.1, rarity=0.8)
    assert t.archetype == "snobivore"


def test_typology_explorer() -> None:
    t = metrics.omnivore_typology(effective_genres=8.0, sprawl=0.1, rarity=0.2)
    assert t.archetype == "explorer"


# ------------------------------------------------------------ sonic signatures


def test_camelot_distribution_counts_and_valence() -> None:
    # C major (key=0, mode=1) = 8B; two of them, valences 0.2 and 0.8 → mean 0.5
    audio = [(0, 1, 0.2), (0, 1, 0.8), (9, 0, 0.4)]  # last is A minor = 8A
    dist = metrics.camelot_distribution(audio)
    codes = {entry["code"]: entry for entry in dist}
    assert codes["8B"]["count"] == 2
    assert codes["8B"]["mean_valence"] == pytest.approx(0.5)
    assert codes["8A"]["count"] == 1
    # sorted by (number, ring): 8A before 8B
    assert [e["code"] for e in dist] == ["8A", "8B"]


def test_camelot_distribution_drops_unmappable() -> None:
    assert metrics.camelot_distribution([(None, None, 0.5)]) == []


def test_mood_grid_quadrant_shares() -> None:
    # 4 points, one in each quadrant
    pairs = [(0.8, 0.8), (0.8, 0.2), (0.2, 0.8), (0.2, 0.2)]
    result = metrics.mood_grid(pairs, size=2)
    assert result["shares"] == {
        "happy_energetic": 0.25,
        "energetic_tense": 0.25,
        "peaceful_content": 0.25,
        "calm_sad": 0.25,
    }
    # 2x2 grid: one count per cell
    assert result["grid"] == [[1, 1], [1, 1]]


def test_tempo_histogram_bands() -> None:
    # 125 → band [120,130); 128 → same band; 72 → [70,80)
    hist = metrics.tempo_histogram([125.0, 128.0, 72.0])
    by_low = {entry["bpm_low"]: entry["count"] for entry in hist}
    assert by_low[120] == 2
    assert by_low[70] == 1
    # bands span 60..200 at width 10 → 14 bands
    assert len(hist) == 14


def test_tempo_histogram_clamps_out_of_range() -> None:
    hist = metrics.tempo_histogram([30.0, 250.0])
    by_low = {entry["bpm_low"]: entry["count"] for entry in hist}
    assert by_low[60] == 1  # 30 clamps up into first band
    assert by_low[190] == 1  # 250 clamps down into last band


def test_feature_ridgelines_bucket_counts() -> None:
    vectors = [
        dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.05),  # bucket 1 at 20 buckets
        dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.95),  # bucket 19
    ]
    ridges = metrics.feature_ridgelines(vectors, buckets=20)
    assert len(ridges) == 9
    energy = next(r for r in ridges if r["feature"] == "energy")
    assert energy["buckets"][1] == 1
    assert energy["buckets"][19] == 1
    assert sum(energy["buckets"]) == 2


# ------------------------------------------------------------------- extremes


def test_extremes_board_longest_shortest_and_feature() -> None:
    tracks = [
        {"track_id": 1, "name": "Short", "artist": "A", "duration_ms": 60_000},
        {"track_id": 2, "name": "Long", "artist": "B", "duration_ms": 300_000},
    ]
    vectors = {
        1: dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.9),
        2: dict.fromkeys(metrics.FINGERPRINT_FEATURES, 0.1),
    }
    board = metrics.extremes_board(tracks, vectors)
    by_label = {entry["label"]: entry for entry in board}
    assert by_label["longest"]["track_id"] == 2
    assert by_label["longest"]["value"] == 300.0
    assert by_label["shortest"]["track_id"] == 1
    # track 1 has higher percentiles → most_energy
    assert by_label["most_energy"]["track_id"] == 1


# --------------------------------------------------------------------- eras


def test_era_profile_decades_and_center() -> None:
    years = [1995, 1998, 2001, 2011, 2011]
    profile = metrics.era_profile(years)
    decades = {d["decade"]: d["count"] for d in profile["decades"]}
    assert decades == {1990: 2, 2000: 1, 2010: 2}
    assert profile["center_of_gravity"] == 2011  # modal
    assert profile["median_year"] == 2001
    assert profile["coming_of_age"] is None


def test_era_profile_coming_of_age_band() -> None:
    # birth 1992 → band 2008..2016; years 2011 and 2011 fall in it (2/5)
    years = [1995, 1998, 2001, 2011, 2011]
    profile = metrics.era_profile(years, birth_year=1992)
    band = profile["coming_of_age"]
    assert band["band_start_year"] == 2008
    assert band["band_end_year"] == 2016
    assert band["count"] == 2
    assert band["share"] == pytest.approx(0.4)


def test_era_profile_empty() -> None:
    profile = metrics.era_profile([])
    assert profile["total"] == 0
    assert profile["decades"] == []


# ------------------------------------------------------------------ genres


def test_genre_shares_normalized_and_ranked() -> None:
    shares = metrics.genre_shares({"house": 3.0, "techno": 1.0}, top=12)
    assert shares == [
        {"genre": "house", "share": 0.75},
        {"genre": "techno", "share": 0.25},
    ]


def test_genre_shares_top_limit() -> None:
    weights = {f"g{i}": float(i + 1) for i in range(20)}
    shares = metrics.genre_shares(weights, top=3)
    assert len(shares) == 3
    # highest weights first
    assert shares[0]["genre"] == "g19"


def test_genre_rarity_weighted_mean() -> None:
    # ranks 1496 → rarity 1.0, 748 → rarity 0.5; weights 1 and 1 → mean 0.75
    weights = {"catstep": 2.0, "house": 2.0}
    ranks = {"catstep": 1496, "house": 748}
    mean, rarest = metrics.genre_rarity(weights, ranks)
    assert mean == pytest.approx(0.75)
    assert rarest[0]["genre"] == "catstep"
    assert rarest[0]["rarity"] == 1.0


def test_genre_rarity_ignores_unranked() -> None:
    mean, rarest = metrics.genre_rarity({"x": 1.0}, {"x": None})
    assert mean == 0.0
    assert rarest == []


# -------------------------------------------------------- collection archaeology


def test_monthly_adds_bucket_and_centroid() -> None:
    adds = [
        ("2024-01", {"acousticness": 0.2, "energy": 0.4, "valence": 0.6}),
        ("2024-01", {"acousticness": 0.4, "energy": 0.6, "valence": 0.8}),
        ("2024-02", None),
    ]
    buckets = metrics.monthly_adds(adds)
    jan = next(b for b in buckets if b["month"] == "2024-01")
    assert jan["count"] == 2
    assert jan["centroid"] == {"acousticness": 0.3, "energy": 0.5, "valence": 0.7}
    feb = next(b for b in buckets if b["month"] == "2024-02")
    assert feb["count"] == 1
    assert feb["centroid"] is None
    # oldest first
    assert [b["month"] for b in buckets] == ["2024-01", "2024-02"]


def test_abandoned_playlists_threshold_and_order() -> None:
    last = {1: ("Fresh", 2), 2: ("Dusty", 12), 3: ("Old", 7)}
    dormant = metrics.abandoned_playlists(last, dormant_months=6)
    assert [entry["playlist_id"] for entry in dormant] == [2, 3]  # dustiest first
    assert all(entry["months_dormant"] >= 6 for entry in dormant)


def test_math_import_used() -> None:
    # guard: entropy uses log2
    assert metrics.shannon_entropy({"a": 1, "b": 3}) == pytest.approx(
        -(0.25 * math.log2(0.25) + 0.75 * math.log2(0.75))
    )
