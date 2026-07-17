"""F6 — per-playlist quality score with an explained sub-score breakdown.

One headline 0..1 quality figure per playlist, blended from four sub-scores
that each answer a distinct curator question. Every sub-score is 0..1 with 1 =
good, so the blend reads directly and each limb gets its own metric_ref for the
web to attach an explain to:

- cohesion   — how tightly the tracks cluster in sound (tight = high).
- uniqueness — freedom from duplicate tracks (no repeats = high).
- freshness  — how recently the playlist was tended (recent add = high).
- flow       — how well the current order transitions (smooth = high).
"""

from datetime import UTC, datetime, timedelta

import pytest

from crate.services.competitive.quality import (
    SUBSCORE_REFS,
    freshness_subscore,
    playlist_quality,
)

pytestmark = pytest.mark.unit

NOW = datetime(2024, 6, 1, tzinfo=UTC)


class TestFreshnessSubscore:
    def test_added_today_is_fresh(self) -> None:
        assert freshness_subscore(NOW, now=NOW) == pytest.approx(1.0)

    def test_dormant_playlist_decays(self) -> None:
        recent = freshness_subscore(NOW - timedelta(days=30), now=NOW)
        stale = freshness_subscore(NOW - timedelta(days=365), now=NOW)
        assert recent > stale
        assert 0.0 <= stale < recent <= 1.0

    def test_never_added_is_zero(self) -> None:
        assert freshness_subscore(None, now=NOW) == 0.0


class TestPlaylistQuality:
    def test_blends_four_subscores_into_headline(self) -> None:
        result = playlist_quality(
            cohesion=0.2,  # tight → high cohesion sub-score
            duplicate_fraction=0.0,  # no dups → uniqueness 1.0
            newest_added_at=NOW,  # fresh → 1.0
            flow_score=90.0,  # smooth → 0.9
            now=NOW,
        )
        subs = {s["ref"]: s["value"] for s in result["subscores"]}
        assert subs["quality_cohesion"] == pytest.approx(0.8)
        assert subs["quality_uniqueness"] == pytest.approx(1.0)
        assert subs["quality_freshness"] == pytest.approx(1.0)
        assert subs["quality_flow"] == pytest.approx(0.9)
        # Headline is the mean of the present sub-scores.
        assert result["score"] == pytest.approx((0.8 + 1.0 + 1.0 + 0.9) / 4, abs=1e-4)

    def test_missing_subscores_are_excluded_not_zeroed(self) -> None:
        # A one-track playlist has no cohesion and no flow; the headline blends
        # only the sub-scores that could be computed, never treating a missing
        # one as a zero that unfairly tanks the score.
        result = playlist_quality(
            cohesion=None,
            duplicate_fraction=0.0,
            newest_added_at=NOW,
            flow_score=None,
            now=NOW,
        )
        refs = {s["ref"] for s in result["subscores"]}
        assert "quality_cohesion" not in refs
        assert "quality_flow" not in refs
        assert result["score"] == pytest.approx(1.0)  # mean of uniqueness + freshness

    def test_all_subscores_missing_gives_null_headline(self) -> None:
        result = playlist_quality(
            cohesion=None,
            duplicate_fraction=None,
            newest_added_at=None,
            flow_score=None,
            now=NOW,
        )
        # Freshness of None is 0.0 (a real signal: never tended), so the only
        # unavailable ones are cohesion/uniqueness/flow. Freshness still counts.
        refs = {s["ref"] for s in result["subscores"]}
        assert refs == {"quality_freshness"}
        assert result["score"] == pytest.approx(0.0)

    def test_duplicate_fraction_lowers_uniqueness(self) -> None:
        clean = playlist_quality(
            cohesion=0.5, duplicate_fraction=0.0, newest_added_at=NOW, flow_score=50.0, now=NOW
        )
        dupey = playlist_quality(
            cohesion=0.5, duplicate_fraction=0.4, newest_added_at=NOW, flow_score=50.0, now=NOW
        )
        clean_u = next(s["value"] for s in clean["subscores"] if s["ref"] == "quality_uniqueness")
        dupey_u = next(s["value"] for s in dupey["subscores"] if s["ref"] == "quality_uniqueness")
        assert clean_u == pytest.approx(1.0)
        assert dupey_u == pytest.approx(0.6)

    def test_every_subscore_ref_is_registered(self) -> None:
        result = playlist_quality(
            cohesion=0.2, duplicate_fraction=0.0, newest_added_at=NOW, flow_score=90.0, now=NOW
        )
        for sub in result["subscores"]:
            assert sub["ref"] in SUBSCORE_REFS
