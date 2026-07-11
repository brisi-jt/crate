"""Camelot-wheel key compatibility, BPM transition scoring, greedy reorder.

Camelot reference points (pitch class, mode) -> wheel position:
C major = 8B, A minor = 8A, G major = 9B, E minor = 9A.
"""

import pytest

from crate.services.analytics.flow import (
    TrackAudio,
    bpm_score,
    camelot,
    flow_score,
    key_score,
    suggest_order,
    transition_score,
)

pytestmark = pytest.mark.unit


class TestCamelot:
    def test_reference_majors(self) -> None:
        assert camelot(0, 1) == (8, "B")  # C major
        assert camelot(7, 1) == (9, "B")  # G major
        assert camelot(2, 1) == (10, "B")  # D major
        assert camelot(11, 1) == (1, "B")  # B major
        assert camelot(5, 1) == (7, "B")  # F major

    def test_reference_minors(self) -> None:
        assert camelot(9, 0) == (8, "A")  # A minor (relative of C major)
        assert camelot(4, 0) == (9, "A")  # E minor (relative of G major)
        assert camelot(0, 0) == (5, "A")  # C minor (relative of Eb major)

    def test_unknown_key_returns_none(self) -> None:
        assert camelot(None, 1) is None
        assert camelot(0, None) is None
        assert camelot(-1, 1) is None


class TestKeyScore:
    def test_same_key_is_perfect(self) -> None:
        assert key_score((8, "B"), (8, "B")) == pytest.approx(1.0)

    def test_relative_major_minor_is_perfect(self) -> None:
        # Same wheel number, other ring: C major <-> A minor.
        assert key_score((8, "B"), (8, "A")) == pytest.approx(1.0)

    def test_adjacent_number_same_ring(self) -> None:
        # One wheel step: 1 - 1/6
        assert key_score((8, "B"), (9, "B")) == pytest.approx(5 / 6)

    def test_wheel_distance_wraps_circularly(self) -> None:
        # 1 and 12 are adjacent on the wheel.
        assert key_score((12, "B"), (1, "B")) == pytest.approx(5 / 6)

    def test_diagonal_step_pays_ring_penalty(self) -> None:
        # One number step plus a ring switch: effective distance 2.
        assert key_score((8, "B"), (9, "A")) == pytest.approx(4 / 6)

    def test_opposite_side_of_wheel_is_zero(self) -> None:
        assert key_score((8, "B"), (2, "B")) == pytest.approx(0.0)

    def test_unknown_key_is_neutral(self) -> None:
        assert key_score(None, (8, "B")) == pytest.approx(0.5)


class TestBpmScore:
    def test_identical_tempo_is_perfect(self) -> None:
        assert bpm_score(120.0, 120.0) == pytest.approx(1.0)

    def test_small_difference_hand_computed(self) -> None:
        # |120-126|/126 = 0.047619; 1 - 0.047619/0.16 = 0.702381
        assert bpm_score(120.0, 126.0) == pytest.approx(1 - (6 / 126) / 0.16)

    def test_symmetry(self) -> None:
        assert bpm_score(120.0, 126.0) == pytest.approx(bpm_score(126.0, 120.0))

    def test_half_time_counts_as_matching(self) -> None:
        assert bpm_score(60.0, 120.0) == pytest.approx(1.0)
        assert bpm_score(120.0, 60.0) == pytest.approx(1.0)

    def test_far_apart_is_zero(self) -> None:
        assert bpm_score(100.0, 150.0) == pytest.approx(0.0)

    def test_unknown_tempo_is_neutral(self) -> None:
        assert bpm_score(None, 120.0) == pytest.approx(0.5)
        assert bpm_score(120.0, 0.0) == pytest.approx(0.5)


class TestFlowScore:
    def test_transition_score_averages_key_and_bpm_on_0_100(self) -> None:
        a = TrackAudio(track_id=1, tempo=120.0, key=0, mode=1)  # 8B
        b = TrackAudio(track_id=2, tempo=120.0, key=7, mode=1)  # 9B
        # key 5/6, bpm 1.0 -> (0.5*5/6 + 0.5*1) * 100 = 91.666...
        assert transition_score(a, b) == pytest.approx((0.5 * 5 / 6 + 0.5) * 100)

    def test_playlist_flow_is_mean_of_consecutive_transitions(self) -> None:
        tracks = [
            TrackAudio(track_id=1, tempo=120.0, key=0, mode=1),  # 8B
            TrackAudio(track_id=2, tempo=120.0, key=7, mode=1),  # 9B
            TrackAudio(track_id=3, tempo=120.0, key=7, mode=1),  # 9B again
        ]
        # transitions: 91.666..., 100.0 -> mean 95.8333...
        assert flow_score(tracks) == pytest.approx((91.66666 + 100.0) / 2, abs=1e-3)

    def test_single_track_has_no_flow(self) -> None:
        assert flow_score([TrackAudio(track_id=1, tempo=120.0, key=0, mode=1)]) is None


class TestSuggestOrder:
    def test_greedy_reorder_groups_compatible_tempos(self) -> None:
        # Same key everywhere; tempo is the only signal. Greedy from the
        # current opener (100 bpm): 104 is relatively closest (4/104 < 4/100),
        # then 96, and the incompatible 140 lands last.
        tracks = [
            TrackAudio(track_id=1, tempo=100.0, key=0, mode=1),
            TrackAudio(track_id=2, tempo=140.0, key=0, mode=1),
            TrackAudio(track_id=3, tempo=104.0, key=0, mode=1),
            TrackAudio(track_id=4, tempo=96.0, key=0, mode=1),
        ]
        suggestion = suggest_order(tracks)
        assert suggestion is not None
        assert suggestion.order == [1, 3, 4, 2]
        current = flow_score(tracks)
        assert current is not None
        assert suggestion.score > current

    def test_two_or_fewer_tracks_yields_no_suggestion(self) -> None:
        tracks = [
            TrackAudio(track_id=1, tempo=100.0, key=0, mode=1),
            TrackAudio(track_id=2, tempo=140.0, key=0, mode=1),
        ]
        assert suggest_order(tracks) is None

    def test_suggestion_is_deterministic(self) -> None:
        tracks = [
            TrackAudio(track_id=i, tempo=t, key=0, mode=1)
            for i, t in [(1, 100.0), (2, 128.0), (3, 102.0), (4, 125.0), (5, 99.0)]
        ]
        first = suggest_order(tracks)
        second = suggest_order(tracks)
        assert first is not None and second is not None
        assert first.order == second.order
        assert first.score == pytest.approx(second.score)
