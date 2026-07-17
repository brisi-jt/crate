"""Pin candidate pool (P1 api half): a larger tagged pool the client samples.

The client-side sampler enforces max-1-per-family quotas and recently-shown
down-weighting; the api's job is to ship a wide pool (15-25 target) with a
family tag + freshness on every candidate. These tests prove the pool shape and
the tagging, not the sampling.
"""

import pytest

from crate.services.insights import pin_candidates as pc

pytestmark = pytest.mark.unit


def _extended_payload() -> dict:
    """A populated extended payload covering every family."""
    return {
        "coverage": {"play_events": 40, "total_saved": 12, "top_snapshots": 4},
        "play_events": {
            "play_collect_gap": {
                "over_played": [
                    {"track_id": 1, "name": "A", "artist": "x", "plays": 20, "memberships": 1}
                ],
                "over_collected": [
                    {"track_id": 2, "name": "B", "artist": "y", "plays": 1, "memberships": 6}
                ],
                "played_tracks": 30,
            },
            "listening_clock": {"total": 40, "peak_hour": 22, "hours": [], "weekdays": []},
            "rotation_velocity": {"recency_bias": 0.7, "recent_plays": 28, "deep_plays": 12},
            "context_mix": {
                "contexts": [{"context": "playlist", "count": 30, "share": 0.75}],
                "total": 40,
            },
            "play_mood_by_hour": {
                "bands": [{"band": "night", "count": 10, "mean_energy": 0.3, "mean_valence": 0.2}],
                "total": 40,
            },
            "deep_cuts_vs_hits": {"deep_cut_share": 0.65, "deep_cut_plays": 26, "hit_plays": 14},
        },
        "saved": {
            "liked_vs_playlist": {
                "axes": [{"feature": "energy", "liked": 0.8, "playlist": 0.4, "delta": 0.4}],
                "liked_count": 12,
                "playlist_count": 40,
            },
            "save_file_latency": {"median_days": 9.0, "filed_count": 8},
            "unsave_churn": {"churn_rate": 0.15, "removed": 3, "total_saves": 20},
            "orphan_saves": {"orphan_count": 5, "saved_count": 12, "orphans": []},
            "total_saved": 12,
        },
        "feedback": {
            "source_efficacy": [
                {"source": "lastfm", "accept_rate": 0.8, "reviewed": 10, "accept": 8, "reject": 2}
            ],
            "taste_of_yes": {
                "axes": [{"feature": "energy", "accepted": 0.9, "rejected": 0.2, "delta": 0.7}],
                "accepted_count": 8,
                "rejected_count": 2,
            },
            "per_artist_affinity": {
                "loved": [{"artist": "Aphex Twin", "accept_rate": 1.0, "reviews": 4}],
                "disliked": [],
            },
            "candidate_funnel": {"stages": [], "total": 22},
            "curation_totals": {"accept": 8, "reject": 2, "skip": 1},
        },
        "top_items": {
            "top_vs_library": {
                "axes": [{"feature": "energy", "top": 0.7, "library": 0.5, "delta": 0.2}],
                "top_count": 20,
                "library_count": 100,
            },
            "affinity_churn": {"mean_jaccard": 0.6, "transitions": [{"jaccard": 0.6}]},
            "short_vs_long": {"rising": ["a"], "fading": ["b"], "stable": ["c"]},
            "snapshot_count": 4,
        },
        "radio": {
            "keep_rate": {"keep_rate": 0.55, "kept": 11, "skipped": 9, "total": 20, "by_seed": []},
            "discovery_conversion": {"conversion_rate": 0.3, "kept": 3, "discovery_total": 10},
        },
        "journal": {
            "curation_intensity": {
                "edits_per_week": 12.0,
                "undo_rate": 0.1,
                "total": 60,
                "undone": 6,
                "op_mix": [{"op_type": "add_tracks", "count": 40}],
            },
            "bulk_algebra": {
                "operations": [{"operation": "union", "count": 5}],
                "total": 8,
            },
        },
        "cross_table": {
            "listened_vs_neglected": [
                {"playlist_id": 3, "name": "Gamma", "plays": 0, "months_dormant": 14}
            ],
            "calibration_drift": {"features": []},
            "era_add_vs_release": {
                "add_years": [{"add_year": 2024, "count": 30, "median_gap_years": 18.0}],
                "total": 30,
            },
        },
    }


def test_candidate_pool_is_wide() -> None:
    pins = pc.insights_candidates(_extended_payload())
    # a populated library should yield a broad pool (target 15-25).
    assert len(pins) >= 15


def test_every_candidate_is_tagged() -> None:
    pins = pc.insights_candidates(_extended_payload())
    for pin in pins:
        assert pin["family"]  # family tag for max-1/family quota
        assert pin["metric_ref"]
        assert pin["dismissible_id"]
        assert 0.0 <= pin["salience"] <= 1.0


def test_families_are_diverse() -> None:
    pins = pc.insights_candidates(_extended_payload())
    families = {pin["family"] for pin in pins}
    # candidates span most of the seven extended families.
    assert len(families) >= 5


def test_empty_payload_yields_no_candidates() -> None:
    empty = {
        "coverage": {"play_events": 0, "total_saved": 0, "top_snapshots": 0},
        "play_events": {
            "play_collect_gap": {"over_played": [], "over_collected": [], "played_tracks": 0},
            "listening_clock": {"total": 0, "peak_hour": None, "hours": [], "weekdays": []},
            "rotation_velocity": {"recency_bias": None, "recent_plays": 0, "deep_plays": 0},
            "context_mix": {"contexts": [], "total": 0},
            "play_mood_by_hour": {"bands": [], "total": 0},
            "deep_cuts_vs_hits": {"deep_cut_share": None, "deep_cut_plays": 0, "hit_plays": 0},
        },
        "saved": {
            "liked_vs_playlist": {"axes": [], "liked_count": 0, "playlist_count": 0},
            "save_file_latency": {"median_days": None, "filed_count": 0},
            "unsave_churn": {"churn_rate": None, "removed": 0, "total_saves": 0},
            "orphan_saves": {"orphan_count": 0, "saved_count": 0, "orphans": []},
            "total_saved": 0,
        },
        "feedback": {
            "source_efficacy": [],
            "taste_of_yes": {"axes": [], "accepted_count": 0, "rejected_count": 0},
            "per_artist_affinity": {"loved": [], "disliked": []},
            "candidate_funnel": {"stages": [], "total": 0},
            "curation_totals": {"accept": 0, "reject": 0, "skip": 0},
        },
        "top_items": {
            "top_vs_library": {"axes": [], "top_count": 0, "library_count": 0},
            "affinity_churn": {"mean_jaccard": None, "transitions": []},
            "short_vs_long": {"rising": [], "fading": [], "stable": []},
            "snapshot_count": 0,
        },
        "radio": {
            "keep_rate": {"keep_rate": None, "kept": 0, "skipped": 0, "total": 0, "by_seed": []},
            "discovery_conversion": {"conversion_rate": None, "kept": 0, "discovery_total": 0},
        },
        "journal": {
            "curation_intensity": {
                "edits_per_week": None,
                "undo_rate": None,
                "total": 0,
                "undone": 0,
                "op_mix": [],
            },
            "bulk_algebra": {"operations": [], "total": 0},
        },
        "cross_table": {
            "listened_vs_neglected": [],
            "calibration_drift": {"features": []},
            "era_add_vs_release": {"add_years": [], "total": 0},
        },
    }
    assert pc.insights_candidates(empty) == []
