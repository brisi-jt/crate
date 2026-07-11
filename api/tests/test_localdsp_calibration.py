"""Quantile mapping: local-DSP distribution -> ReccoBeats distribution."""

import pytest

from crate.services.enrichment.localdsp import (
    QUANTILE_GRID_SIZE,
    apply_quantile_map,
    fit_quantile_map,
    quantile_grid,
)

pytestmark = pytest.mark.unit


def test_quantile_grid_is_ascending_and_spans_the_data() -> None:
    grid = quantile_grid([5.0, 1.0, 3.0, 2.0, 4.0])
    assert len(grid) == QUANTILE_GRID_SIZE
    assert grid == sorted(grid)
    assert grid[0] == 1.0
    assert grid[-1] == 5.0


def test_fit_maps_median_to_median() -> None:
    local = [float(i) for i in range(11)]  # median 5
    target = [float(i) * 2 + 10 for i in range(11)]  # median 20
    local_anchors, target_anchors = fit_quantile_map(local, target)
    assert apply_quantile_map(local_anchors, target_anchors, 5.0) == pytest.approx(20.0)


def test_map_is_monotone() -> None:
    local = [0.0, 0.2, 0.3, 0.5, 0.6, 0.8, 0.9, 1.0]
    target = [0.1, 0.15, 0.4, 0.45, 0.7, 0.75, 0.9, 0.95]
    la, ta = fit_quantile_map(local, target)
    outputs = [apply_quantile_map(la, ta, x / 20) for x in range(21)]
    assert outputs == sorted(outputs)


def test_values_outside_anchor_range_clamp_to_the_ends() -> None:
    la, ta = fit_quantile_map([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    assert apply_quantile_map(la, ta, -5.0) == pytest.approx(10.0)
    assert apply_quantile_map(la, ta, 99.0) == pytest.approx(30.0)


def test_uniform_shift_is_preserved() -> None:
    local = [i / 10 for i in range(8)]
    target = [v + 0.2 for v in local]
    la, ta = fit_quantile_map(local, target)
    assert apply_quantile_map(la, ta, 0.35) == pytest.approx(0.55)


def test_mismatched_sample_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        fit_quantile_map([1.0, 2.0], [1.0])


def test_empty_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        quantile_grid([])
