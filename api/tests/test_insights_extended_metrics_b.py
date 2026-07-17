"""Hand-computed micro-fixtures for I7-I17 (saved / feedback / top-items)."""

import pytest

from crate.services.insights import metrics_extended as mx

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- I7 liked vs playlist fp


def test_liked_vs_playlist_fingerprint_delta() -> None:
    liked = [dict.fromkeys(mx.FINGERPRINT_FEATURES, 0.8)]
    playlist = [dict.fromkeys(mx.FINGERPRINT_FEATURES, 0.4)]
    result = mx.liked_vs_playlist_fingerprint(liked, playlist)
    by_feature = {e["feature"]: e for e in result["axes"]}
    assert by_feature["energy"]["liked"] == pytest.approx(0.8)
    assert by_feature["energy"]["playlist"] == pytest.approx(0.4)
    assert by_feature["energy"]["delta"] == pytest.approx(0.4)
    assert result["liked_count"] == 1
    assert result["playlist_count"] == 1


def test_liked_vs_playlist_fingerprint_empty() -> None:
    result = mx.liked_vs_playlist_fingerprint([], [])
    assert result["axes"] == []


# ---------------------------------------------------------------- I8 save->file latency


def test_save_file_latency_median_days() -> None:
    # latencies in days: 2, 4, 10 -> median 4.
    latencies = [2.0, 4.0, 10.0]
    result = mx.save_file_latency(latencies)
    assert result["median_days"] == pytest.approx(4.0)
    assert result["filed_count"] == 3


def test_save_file_latency_empty() -> None:
    result = mx.save_file_latency([])
    assert result["median_days"] is None
    assert result["filed_count"] == 0


# ---------------------------------------------------------------- I9 unsave churn


def test_unsave_churn_rate() -> None:
    # 3 removed of 10 total saves -> churn 0.3.
    result = mx.unsave_churn(total_saves=10, removed=3)
    assert result["churn_rate"] == pytest.approx(0.3)
    assert result["removed"] == 3


def test_unsave_churn_empty() -> None:
    result = mx.unsave_churn(total_saves=0, removed=0)
    assert result["churn_rate"] is None


# ---------------------------------------------------------------- I10 orphan saves


def test_orphan_saves_counts_unfiled() -> None:
    # saved track ids 1,2,3; filed set {1} -> 2 orphans.
    result = mx.orphan_saves(
        saved_ids={1, 2, 3},
        filed_ids={1},
        track_meta={2: {"name": "B", "artist": "y"}, 3: {"name": "C", "artist": "z"}},
    )
    assert result["orphan_count"] == 2
    assert result["saved_count"] == 3
    assert {e["track_id"] for e in result["orphans"]} == {2, 3}


def test_orphan_saves_none() -> None:
    result = mx.orphan_saves(saved_ids={1}, filed_ids={1}, track_meta={})
    assert result["orphan_count"] == 0


# ---------------------------------------------------------------- I11 source efficacy


def test_source_efficacy_accept_rate_per_source() -> None:
    # lastfm: 3 accept / 1 reject -> rate .75; enao: 0 accept / 2 reject -> 0.
    tallies = {
        "lastfm": {"accept": 3, "reject": 1, "skip": 0},
        "enao": {"accept": 0, "reject": 2, "skip": 0},
    }
    board = mx.source_efficacy(tallies)
    by_source = {e["source"]: e for e in board}
    assert by_source["lastfm"]["accept_rate"] == pytest.approx(0.75)
    assert by_source["enao"]["accept_rate"] == pytest.approx(0.0)
    # sorted best first.
    assert board[0]["source"] == "lastfm"


def test_source_efficacy_empty() -> None:
    assert mx.source_efficacy({}) == []


# ---------------------------------------------------------------- I12 taste of yes


def test_taste_of_yes_accepted_vs_rejected() -> None:
    accepted = [dict.fromkeys(mx.FINGERPRINT_FEATURES, 0.9)]
    rejected = [dict.fromkeys(mx.FINGERPRINT_FEATURES, 0.2)]
    result = mx.taste_of_yes(accepted, rejected)
    by_feature = {e["feature"]: e for e in result["axes"]}
    assert by_feature["energy"]["accepted"] == pytest.approx(0.9)
    assert by_feature["energy"]["rejected"] == pytest.approx(0.2)
    assert result["accepted_count"] == 1
    assert result["rejected_count"] == 1


def test_taste_of_yes_empty() -> None:
    result = mx.taste_of_yes([], [])
    assert result["axes"] == []


# ---------------------------------------------------------------- I13 per-artist affinity


def test_per_artist_affinity_ranks_by_accept_rate() -> None:
    tallies = {
        "Aphex Twin": {"accept": 4, "reject": 0},
        "Nickelback": {"accept": 0, "reject": 3},
    }
    result = mx.per_artist_affinity(tallies, top=5, min_reviews=1)
    loved = {e["artist"] for e in result["loved"]}
    disliked = {e["artist"] for e in result["disliked"]}
    assert "Aphex Twin" in loved
    assert "Nickelback" in disliked


def test_per_artist_affinity_respects_min_reviews() -> None:
    tallies = {"OneReview": {"accept": 1, "reject": 0}}
    result = mx.per_artist_affinity(tallies, min_reviews=2)
    assert result["loved"] == []


# ---------------------------------------------------------------- I14 candidate funnel


def test_candidate_funnel_status_counts() -> None:
    counts = {"pending": 10, "resolved": 6, "accepted": 3, "rejected": 2, "unresolvable": 1}
    funnel = mx.candidate_funnel(counts)
    by_stage = {s["stage"]: s["count"] for s in funnel["stages"]}
    assert by_stage["pending"] == 10
    assert by_stage["accepted"] == 3
    assert funnel["total"] == 22


def test_candidate_funnel_empty() -> None:
    funnel = mx.candidate_funnel({})
    assert funnel["total"] == 0


# ---------------------------------------------------------------- I15 top vs library


def test_top_items_sound_vs_library() -> None:
    top = [dict.fromkeys(mx.FINGERPRINT_FEATURES, 0.7)]
    library = [dict.fromkeys(mx.FINGERPRINT_FEATURES, 0.5)]
    result = mx.top_items_sound(top, library)
    by_feature = {e["feature"]: e for e in result["axes"]}
    assert by_feature["energy"]["top"] == pytest.approx(0.7)
    assert by_feature["energy"]["library"] == pytest.approx(0.5)
    assert by_feature["energy"]["delta"] == pytest.approx(0.2)


def test_top_items_sound_empty() -> None:
    assert mx.top_items_sound([], [])["axes"] == []


# ---------------------------------------------------------------- I16 affinity churn


def test_affinity_churn_jaccard() -> None:
    # successive snapshots: {a,b,c} then {b,c,d} -> Jaccard 2/4 = 0.5.
    snapshots = [["a", "b", "c"], ["b", "c", "d"]]
    result = mx.affinity_churn(snapshots)
    assert result["transitions"][0]["jaccard"] == pytest.approx(0.5)
    assert result["mean_jaccard"] == pytest.approx(0.5)


def test_affinity_churn_single_snapshot() -> None:
    result = mx.affinity_churn([["a"]])
    assert result["transitions"] == []
    assert result["mean_jaccard"] is None


# ---------------------------------------------------------------- I17 short vs long


def test_short_vs_long_divergence() -> None:
    # current obsessions = in short but not long.
    result = mx.short_vs_long_divergence(short=["a", "b", "c"], long=["b", "c", "d"])
    assert set(result["rising"]) == {"a"}
    assert set(result["fading"]) == {"d"}
    assert set(result["stable"]) == {"b", "c"}


def test_short_vs_long_divergence_empty() -> None:
    result = mx.short_vs_long_divergence(short=[], long=[])
    assert result["rising"] == []
