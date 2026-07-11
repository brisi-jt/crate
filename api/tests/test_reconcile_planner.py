"""Property suite for the reconcile planner.

plan_reconcile(current, target) emits remove/add/move steps that, executed
under Spotify's API semantics (remove = all occurrences of a URI, moves index
the pre-move list), transform `current` into exactly `target` — membership
AND order.
"""

import random

import pytest

from crate.services.mutations.planner import (
    AddStep,
    MoveStep,
    RemoveStep,
    plan_reconcile,
)
from tests.mutation_fakes import spotify_reorder

pytestmark = pytest.mark.unit


def simulate(current: list[str], steps) -> list[str]:
    """Execute a plan with Spotify's exact API semantics."""
    state = list(current)
    for step in steps:
        if isinstance(step, RemoveStep):
            drop = set(step.uris)
            state = [u for u in state if u not in drop]
        elif isinstance(step, AddStep):
            if step.position is None:
                state.extend(step.uris)
            else:
                state[step.position : step.position] = list(step.uris)
        elif isinstance(step, MoveStep):
            state = spotify_reorder(state, step.range_start, step.insert_before)
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unknown step {step!r}")
    return state


def assert_reconciles(current: list[str], target: list[str]) -> None:
    steps = plan_reconcile(current, target)
    assert simulate(current, steps) == target


# -- explicit cases -----------------------------------------------------------


def test_noop_produces_empty_plan() -> None:
    assert plan_reconcile(["a", "b"], ["a", "b"]) == []


def test_pure_append_is_single_add_step() -> None:
    steps = plan_reconcile(["a", "b"], ["a", "b", "c", "d"])
    assert steps == [AddStep(uris=("c", "d"), position=None)]


def test_pure_remove_is_single_remove_step() -> None:
    steps = plan_reconcile(["a", "b", "c"], ["b"])
    assert steps == [RemoveStep(uris=("a", "c"))]


def test_insert_at_position() -> None:
    assert_reconciles(["a", "b", "c"], ["a", "x", "b", "c"])


def test_remove_one_occurrence_of_duplicate() -> None:
    # Spotify's remove drops ALL occurrences — the plan must re-add the kept one.
    assert_reconciles(["a", "b", "a", "c"], ["a", "b", "c"])


def test_pure_reorder_uses_moves_only() -> None:
    current = ["a", "b", "c", "d"]
    target = ["d", "b", "a", "c"]
    steps = plan_reconcile(current, target)
    assert all(isinstance(s, MoveStep) for s in steps)
    assert simulate(current, steps) == target


def test_reverse_order() -> None:
    assert_reconciles(["a", "b", "c", "d", "e"], ["e", "d", "c", "b", "a"])


def test_full_replacement() -> None:
    assert_reconciles(["a", "b"], ["x", "y", "z"])


def test_empty_to_populated_and_back() -> None:
    assert_reconciles([], ["a", "b", "a"])
    assert_reconciles(["a", "b", "a"], [])


def test_duplicate_count_increase() -> None:
    assert_reconciles(["a", "b"], ["a", "b", "a", "a"])


def test_duplicate_count_decrease_keeps_order() -> None:
    assert_reconciles(["a", "x", "a", "y", "a"], ["x", "a", "y"])


# -- randomized state machine -------------------------------------------------


def test_randomized_reconcile_property() -> None:
    rng = random.Random(42)
    alphabet = [f"t{i}" for i in range(12)]
    for _ in range(300):
        current = [rng.choice(alphabet) for _ in range(rng.randint(0, 15))]
        target = [rng.choice(alphabet) for _ in range(rng.randint(0, 15))]
        assert_reconciles(current, target)


def test_randomized_permutations() -> None:
    rng = random.Random(7)
    for _ in range(100):
        n = rng.randint(2, 12)
        current = [f"t{i}" for i in range(n)]
        target = current[:]
        rng.shuffle(target)
        steps = plan_reconcile(current, target)
        # A permutation never needs adds or removes.
        assert all(isinstance(s, MoveStep) for s in steps)
        assert simulate(current, steps) == target
