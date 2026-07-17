"""F5 — taste drift: current sound vs a past self.

MusicTaste.space compares two people; F5 reframes it as a solo, temporal
comparison — 2026-you vs 2023-you — which sidesteps crate's 5-user cap and is
grounded in the top-items history crate already captures. A historical
fingerprint is the mean feature vector of a past top-tracks snapshot; the
comparison is its per-axis delta against the current library fingerprint.

Pure transforms over already-computed percentile vectors; the snapshot reads
and track resolution live in the engine.
"""

import pytest

from crate.services.competitive.drift import fingerprint_delta, fingerprint_of

pytestmark = pytest.mark.unit

FEATURES = ("energy", "valence", "acousticness")


class TestFingerprintOf:
    def test_mean_of_member_vectors(self) -> None:
        vectors = {
            1: {"energy": 0.8, "valence": 0.6, "acousticness": 0.2},
            2: {"energy": 0.4, "valence": 0.4, "acousticness": 0.4},
        }
        fp = fingerprint_of([1, 2], vectors, FEATURES)
        assert fp == {"energy": 0.6, "valence": 0.5, "acousticness": 0.3}

    def test_skips_unenriched_tracks(self) -> None:
        vectors = {1: {"energy": 0.8, "valence": 0.6, "acousticness": 0.2}}
        fp = fingerprint_of([1, 99], vectors, FEATURES)  # 99 has no vector
        assert fp == {"energy": 0.8, "valence": 0.6, "acousticness": 0.2}

    def test_no_enriched_tracks_is_none(self) -> None:
        assert fingerprint_of([99], {}, FEATURES) is None


class TestFingerprintDelta:
    def test_per_axis_delta_now_minus_then(self) -> None:
        now = {"energy": 0.7, "valence": 0.5, "acousticness": 0.3}
        then = {"energy": 0.5, "valence": 0.5, "acousticness": 0.6}
        result = fingerprint_delta(now, then, FEATURES)
        assert result is not None
        by_axis = {a["feature"]: a for a in result["axes"]}
        assert by_axis["energy"]["delta"] == pytest.approx(0.2)
        assert by_axis["valence"]["delta"] == pytest.approx(0.0)
        assert by_axis["acousticness"]["delta"] == pytest.approx(-0.3)

    def test_distance_summarizes_overall_movement(self) -> None:
        now = {"energy": 0.7, "valence": 0.5, "acousticness": 0.3}
        then = {"energy": 0.5, "valence": 0.5, "acousticness": 0.6}
        stable = fingerprint_delta(now, now, FEATURES)
        moved = fingerprint_delta(now, then, FEATURES)
        assert stable is not None and moved is not None
        assert stable["distance"] == pytest.approx(0.0)
        assert moved["distance"] > 0.0

    def test_biggest_mover_surfaced(self) -> None:
        now = {"energy": 0.7, "valence": 0.5, "acousticness": 0.3}
        then = {"energy": 0.5, "valence": 0.5, "acousticness": 0.6}
        result = fingerprint_delta(now, then, FEATURES)
        assert result is not None
        # acousticness moved most (0.3 vs 0.2).
        assert result["biggest_mover"]["feature"] == "acousticness"

    def test_missing_side_is_none(self) -> None:
        assert fingerprint_delta(None, {"energy": 0.5}, FEATURES) is None
        assert fingerprint_delta({"energy": 0.5}, None, FEATURES) is None
