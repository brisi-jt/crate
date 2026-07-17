"""Hand-computed micro-fixtures for I18-I24 (radio / journal / calibration / era)."""

import pytest

from crate.services.insights import metrics_extended as mx

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- I18 radio keep rate


def test_radio_keep_rate_overall_and_by_seed() -> None:
    # two sessions: playlist-seed (kept 2 skip 1), genre-seed (kept 0 skip 2).
    per_seed = {
        "playlist": {"kept": 2, "skipped": 1},
        "genre": {"kept": 0, "skipped": 2},
    }
    result = mx.radio_keep_rate(per_seed)
    assert result["kept"] == 2
    assert result["skipped"] == 3
    assert result["keep_rate"] == pytest.approx(2 / 5)
    by_seed = {e["seed_kind"]: e for e in result["by_seed"]}
    assert by_seed["playlist"]["keep_rate"] == pytest.approx(0.6667)
    assert by_seed["genre"]["keep_rate"] == pytest.approx(0.0)


def test_radio_keep_rate_empty() -> None:
    result = mx.radio_keep_rate({})
    assert result["total"] == 0
    assert result["keep_rate"] is None


# ---------------------------------------------------------------- I19 discovery conversion


def test_discovery_conversion_share_kept() -> None:
    # 10 discovery items, 4 kept -> conversion 0.4.
    result = mx.discovery_conversion(discovery_total=10, discovery_kept=4)
    assert result["conversion_rate"] == pytest.approx(0.4)
    assert result["kept"] == 4


def test_discovery_conversion_empty() -> None:
    result = mx.discovery_conversion(discovery_total=0, discovery_kept=0)
    assert result["conversion_rate"] is None


# ---------------------------------------------------------------- I20 curation intensity


def test_curation_intensity_op_mix_and_undo_rate() -> None:
    # op counts + 2 undone of 10 -> undo rate 0.2.
    op_counts = {"add_tracks": 6, "remove_tracks": 2, "bulk": 2}
    result = mx.curation_intensity(op_counts, undone=2, total=10, weeks=2.0)
    by_op = {e["op_type"]: e["count"] for e in result["op_mix"]}
    assert by_op["add_tracks"] == 6
    assert result["undo_rate"] == pytest.approx(0.2)
    assert result["edits_per_week"] == pytest.approx(5.0)


def test_curation_intensity_empty() -> None:
    result = mx.curation_intensity({}, undone=0, total=0, weeks=0.0)
    assert result["undo_rate"] is None
    assert result["edits_per_week"] is None


# ---------------------------------------------------------------- I21 bulk-algebra usage


def test_bulk_algebra_usage_counts() -> None:
    op_counts = {"union": 3, "difference": 1, "dedupe": 2}
    result = mx.bulk_algebra_usage(op_counts)
    by_op = {e["operation"]: e["count"] for e in result["operations"]}
    assert by_op["union"] == 3
    assert result["total"] == 6
    # sorted most-used first.
    assert result["operations"][0]["operation"] == "union"


def test_bulk_algebra_usage_empty() -> None:
    result = mx.bulk_algebra_usage({})
    assert result["total"] == 0


# ---------------------------------------------------------------- I23 calibration drift


def test_calibration_drift_spread_over_time() -> None:
    # two snapshots of energy p10/p90: spread 0.2 then 0.6 -> widening.
    series = [
        {"captured_at": "2024-01", "feature": "energy", "p10": 0.4, "p90": 0.6},
        {"captured_at": "2024-06", "feature": "energy", "p10": 0.2, "p90": 0.8},
    ]
    result = mx.calibration_drift(series)
    energy = next(f for f in result["features"] if f["feature"] == "energy")
    assert energy["points"][0]["spread"] == pytest.approx(0.2)
    assert energy["points"][1]["spread"] == pytest.approx(0.6)
    assert energy["spread_delta"] == pytest.approx(0.4)


def test_calibration_drift_empty() -> None:
    result = mx.calibration_drift([])
    assert result["features"] == []


# ---------------------------------------------------------------- I24 era of add vs release


def test_era_add_vs_release_nostalgia_waves() -> None:
    # adds in 2024 of tracks released 1990, 2024 -> one nostalgic (34y gap), one current.
    pairs = [(2024, 1990), (2024, 2024), (2024, 2000)]
    result = mx.era_add_vs_release(pairs)
    by_year = {b["add_year"]: b for b in result["add_years"]}
    assert by_year[2024]["count"] == 3
    # median gap across (34, 0, 24) = 24.
    assert by_year[2024]["median_gap_years"] == pytest.approx(24)
    assert result["total"] == 3


def test_era_add_vs_release_empty() -> None:
    result = mx.era_add_vs_release([])
    assert result["add_years"] == []
    assert result["total"] == 0
