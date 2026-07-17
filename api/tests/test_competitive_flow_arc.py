"""F4 — flow sequencer upgrade: mood-arc ordering + artist separation.

The base flow reorder (analytics/flow.suggest_order) optimises key + tempo
transitions only. F4 layers two DJ-grade constraints on the same Camelot/BPM
machinery:

- mood arc          — bias the order toward an energy trajectory (rise, fall,
                      or a peak in the middle), so a set builds and releases
                      instead of wandering.
- artist separation — penalise adjacent (and near-adjacent) tracks by the same
                      artist, so one artist never clumps.

Pure over ArcTrack inputs; the ORM read and the journaled reorder write live in
the engine + router (F4's output is a range-move through MutationService.reorder,
never a parallel write path).
"""

import pytest

from crate.services.competitive.flow_arc import (
    ArcMood,
    ArcTrack,
    arc_target,
    suggest_arc_order,
)

pytestmark = pytest.mark.unit


def _t(tid: int, energy: float, artist: str, tempo: float = 120.0, key: int = 0) -> ArcTrack:
    return ArcTrack(track_id=tid, tempo=tempo, key=key, mode=1, energy=energy, artist_key=artist)


class TestArcTarget:
    def test_rising_arc_increases(self) -> None:
        targets = [arc_target(ArcMood.rising, i, 5) for i in range(5)]
        assert targets == sorted(targets)
        assert targets[0] < targets[-1]

    def test_falling_arc_decreases(self) -> None:
        targets = [arc_target(ArcMood.falling, i, 5) for i in range(5)]
        assert targets == sorted(targets, reverse=True)

    def test_peak_arc_rises_then_falls(self) -> None:
        targets = [arc_target(ArcMood.peak, i, 5) for i in range(5)]
        assert targets[2] == max(targets)  # apex mid-set
        assert targets[0] < targets[2] and targets[-1] < targets[2]


class TestSuggestArcOrder:
    def test_rising_arc_orders_by_energy(self) -> None:
        # Same artist-free, same key+tempo → only the mood arc discriminates.
        # A rising arc should put low-energy first, high-energy last.
        tracks = [
            _t(1, energy=0.9, artist="a"),
            _t(2, energy=0.1, artist="b"),
            _t(3, energy=0.5, artist="c"),
        ]
        suggestion = suggest_arc_order(tracks, mood=ArcMood.rising)
        assert suggestion is not None
        assert suggestion.order == [2, 3, 1]

    def test_falling_arc_orders_by_descending_energy(self) -> None:
        tracks = [
            _t(1, energy=0.1, artist="a"),
            _t(2, energy=0.9, artist="b"),
            _t(3, energy=0.5, artist="c"),
        ]
        suggestion = suggest_arc_order(tracks, mood=ArcMood.falling)
        assert suggestion is not None
        assert suggestion.order == [2, 3, 1]

    def test_artist_separation_breaks_up_clumps(self) -> None:
        # Four tracks, two by artist "x". With separation on, the two "x" tracks
        # should not sit adjacent when an alternative exists.
        tracks = [
            _t(1, energy=0.5, artist="x"),
            _t(2, energy=0.5, artist="x"),
            _t(3, energy=0.5, artist="y"),
            _t(4, energy=0.5, artist="z"),
        ]
        suggestion = suggest_arc_order(tracks, mood=ArcMood.rising)
        assert suggestion is not None
        order = suggestion.order
        x_positions = [i for i, tid in enumerate(order) if tid in (1, 2)]
        assert abs(x_positions[0] - x_positions[1]) > 1

    def test_returns_permutation_of_input(self) -> None:
        tracks = [_t(i, energy=i / 10, artist=chr(97 + i)) for i in range(6)]
        suggestion = suggest_arc_order(tracks, mood=ArcMood.peak)
        assert suggestion is not None
        assert sorted(suggestion.order) == sorted(t.track_id for t in tracks)

    def test_deterministic(self) -> None:
        tracks = [_t(i, energy=(i * 7 % 10) / 10, artist=chr(97 + i % 3)) for i in range(8)]
        a = suggest_arc_order(tracks, mood=ArcMood.rising)
        b = suggest_arc_order(tracks, mood=ArcMood.rising)
        assert a is not None and b is not None
        assert a.order == b.order

    def test_reports_flow_and_separation_quality(self) -> None:
        tracks = [_t(i, energy=i / 10, artist=chr(97 + i)) for i in range(5)]
        suggestion = suggest_arc_order(tracks, mood=ArcMood.rising)
        assert suggestion is not None
        # Carries the base flow score (key/tempo) so the UI can show the tradeoff.
        assert 0.0 <= suggestion.flow_score <= 100.0
        # And whether any same-artist tracks remained adjacent (0 here — all uniq).
        assert suggestion.adjacent_artist_repeats == 0

    def test_too_few_tracks_yields_no_suggestion(self) -> None:
        assert suggest_arc_order([_t(1, 0.5, "a"), _t(2, 0.5, "b")], mood=ArcMood.rising) is None
