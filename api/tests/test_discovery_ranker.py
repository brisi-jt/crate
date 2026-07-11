"""Ranker unit suite: deterministic ordering, component bounds, feedback shift.

The ranker is a pure function of (candidate vectors, playlist centroid,
affinity, suggestion counts, feedback tallies) — same inputs must produce the
same ordering, byte for byte.
"""

import math

import pytest

from crate.services.discovery.ranker import (
    FEEDBACK_SPAN,
    NOVELTY_CAP,
    NOVELTY_STEP,
    FitBreakdown,
    RankInput,
    feedback_adjustment,
    fit_breakdown,
    rank,
)

pytestmark = pytest.mark.unit

FEATURES = ("energy", "valence", "acousticness")


def vec(energy: float, valence: float, acousticness: float) -> dict[str, float]:
    return {"energy": energy, "valence": valence, "acousticness": acousticness}


CENTROID = vec(0.8, 0.6, 0.1)


def make_input(
    candidate_id: int,
    vector: dict[str, float],
    *,
    affinity: float = 0.0,
    prior_suggestions: int = 0,
    accepts: int = 0,
    rejects: int = 0,
) -> RankInput:
    return RankInput(
        candidate_id=candidate_id,
        vector=vector,
        affinity=affinity,
        prior_suggestions=prior_suggestions,
        accepts=accepts,
        rejects=rejects,
    )


# ------------------------------------------------------------- breakdown math


def test_perfect_match_scores_full_proximity() -> None:
    result = fit_breakdown(make_input(1, dict(CENTROID)), CENTROID)
    assert result.proximity == pytest.approx(1.0)
    assert result.novelty == 0.0
    assert result.feedback == pytest.approx(0.0)
    assert result.fit == pytest.approx(0.7)  # proximity weight alone


def test_opposite_corner_scores_zero_proximity() -> None:
    result = fit_breakdown(make_input(1, vec(0.0, 0.0, 1.0)), vec(1.0, 1.0, 0.0))
    assert result.proximity == pytest.approx(0.0)
    assert result.fit == pytest.approx(0.0)


def test_hand_computed_breakdown() -> None:
    # distance = sqrt(0.2² + 0.1² + 0.1²) = sqrt(0.06); d = 3 features.
    candidate = vec(0.6, 0.5, 0.2)
    result = fit_breakdown(make_input(1, candidate, affinity=0.5, prior_suggestions=2), CENTROID)
    expected_proximity = 1 - math.sqrt(0.06) / math.sqrt(3)
    assert result.proximity == pytest.approx(expected_proximity)
    assert result.affinity == 0.5
    assert result.novelty == pytest.approx(2 * NOVELTY_STEP)
    assert result.fit == pytest.approx(0.7 * expected_proximity + 0.3 * 0.5 - 2 * NOVELTY_STEP)


def test_novelty_penalty_is_capped() -> None:
    result = fit_breakdown(make_input(1, dict(CENTROID), prior_suggestions=99), CENTROID)
    assert result.novelty == pytest.approx(NOVELTY_CAP)


def test_fit_is_clamped_to_unit_interval() -> None:
    floor = fit_breakdown(
        make_input(1, vec(0.0, 0.0, 1.0), prior_suggestions=99, rejects=10),
        vec(1.0, 1.0, 0.0),
    )
    assert floor.fit == 0.0
    ceiling = fit_breakdown(make_input(1, dict(CENTROID), affinity=1.0, accepts=10), CENTROID)
    assert ceiling.fit == 1.0


def test_breakdown_is_a_named_shape() -> None:
    result = fit_breakdown(make_input(1, dict(CENTROID)), CENTROID)
    assert isinstance(result, FitBreakdown)
    assert {"proximity", "affinity", "novelty", "feedback", "fit"} <= set(result.as_dict())


# ------------------------------------------------------------------- feedback


def test_feedback_neutral_without_history() -> None:
    assert feedback_adjustment(0, 0) == pytest.approx(0.0)


def test_feedback_rewards_accepts_and_punishes_rejects_symmetrically() -> None:
    assert feedback_adjustment(1, 0) == pytest.approx(-feedback_adjustment(0, 1))
    assert feedback_adjustment(1, 0) > 0
    assert feedback_adjustment(0, 1) < 0


def test_feedback_is_bounded_by_span() -> None:
    assert feedback_adjustment(1000, 0) == pytest.approx(FEEDBACK_SPAN, abs=1e-6)
    assert feedback_adjustment(0, 1000) == pytest.approx(-FEEDBACK_SPAN, abs=1e-6)


def test_single_reject_strictly_lowers_fit() -> None:
    clean = fit_breakdown(make_input(1, vec(0.7, 0.6, 0.2)), CENTROID)
    rejected = fit_breakdown(make_input(1, vec(0.7, 0.6, 0.2), rejects=1), CENTROID)
    assert rejected.fit < clean.fit


# ---------------------------------------------------------------- determinism


FIXTURE_QUEUE = [
    make_input(11, vec(0.78, 0.62, 0.12), affinity=0.9),  # near-centroid + affine
    make_input(12, vec(0.80, 0.60, 0.10), affinity=0.0),  # exact centroid, no edge
    make_input(13, vec(0.55, 0.40, 0.30), affinity=0.3),
    make_input(14, vec(0.20, 0.30, 0.90), affinity=0.0),  # far corner
    make_input(15, vec(0.78, 0.62, 0.12), affinity=0.9, prior_suggestions=4),
]


def test_rank_produces_exact_expected_ordering() -> None:
    ordered = rank(FIXTURE_QUEUE, CENTROID)
    assert [entry.candidate_id for entry in ordered] == [11, 15, 12, 13, 14]


def test_rank_is_deterministic_across_runs_and_input_order() -> None:
    first = [(e.candidate_id, e.breakdown.fit) for e in rank(FIXTURE_QUEUE, CENTROID)]
    second = [(e.candidate_id, e.breakdown.fit) for e in rank(FIXTURE_QUEUE, CENTROID)]
    reversed_input = [
        (e.candidate_id, e.breakdown.fit) for e in rank(list(reversed(FIXTURE_QUEUE)), CENTROID)
    ]
    assert first == second == reversed_input


def test_rank_breaks_fit_ties_by_candidate_id() -> None:
    twins = [
        make_input(22, dict(CENTROID)),
        make_input(21, dict(CENTROID)),
    ]
    ordered = rank(twins, CENTROID)
    assert [entry.candidate_id for entry in ordered] == [21, 22]


def test_missing_features_take_the_neutral_rank() -> None:
    # A candidate with no vector ranks from the library-median point, never NaN.
    result = fit_breakdown(make_input(1, {}), CENTROID)
    expected = 1 - math.sqrt(0.3**2 + 0.1**2 + 0.4**2) / math.sqrt(3)
    assert result.proximity == pytest.approx(expected)
