"""F1 — listening-rhythm aggregations over play_events.

The dashboard reuses the I2 listening_clock primitive for the hour/weekday
strips and layers on the counts stats.fm/volt.fm charge for: total plays,
distinct tracks, minutes listened, listening streaks (consecutive days with a
play), and top played tracks. Every figure is a pure transform of a list of
plays; the ORM read (and the range filter) lives in the engine.

Minutes are exact when ``ms_played`` is present (GDPR imports carry it) and
estimated from a nominal track length when it is absent (live captures don't
record duration) — the report flags which, never silently mixing them.
"""

from datetime import datetime

import pytest

from crate.services.competitive.rhythm import (
    NOMINAL_TRACK_MS,
    listening_streaks,
    minutes_listened,
    rhythm_report,
)

pytestmark = pytest.mark.unit


def _play(track_id: int, when: datetime, ms: int | None = None) -> dict:
    return {"track_id": track_id, "played_at": when, "ms_played": ms}


class TestMinutesListened:
    def test_uses_ms_played_when_present(self) -> None:
        plays = [_play(1, datetime(2024, 6, 1), ms=180_000)]  # 3 minutes
        result = minutes_listened(plays)
        assert result["minutes"] == pytest.approx(3.0)
        assert result["estimated"] is False

    def test_estimates_from_nominal_when_ms_absent(self) -> None:
        plays = [_play(1, datetime(2024, 6, 1)), _play(2, datetime(2024, 6, 1))]
        result = minutes_listened(plays)
        assert result["minutes"] == pytest.approx(2 * NOMINAL_TRACK_MS / 60_000)
        assert result["estimated"] is True

    def test_mixed_flags_estimated(self) -> None:
        plays = [_play(1, datetime(2024, 6, 1), ms=60_000), _play(2, datetime(2024, 6, 1))]
        # Any missing ms means the total leans on an estimate.
        assert minutes_listened(plays)["estimated"] is True

    def test_empty_is_zero(self) -> None:
        result = minutes_listened([])
        assert result["minutes"] == 0.0
        assert result["estimated"] is False


class TestListeningStreaks:
    def test_consecutive_days_count_as_one_streak(self) -> None:
        days = [datetime(2024, 6, d) for d in (1, 2, 3)]
        result = listening_streaks(days)
        assert result["longest"] == 3
        assert result["current"] == 3

    def test_gap_breaks_the_streak(self) -> None:
        days = [datetime(2024, 6, d) for d in (1, 2, 5, 6)]
        result = listening_streaks(days)
        assert result["longest"] == 2

    def test_multiple_plays_same_day_count_once(self) -> None:
        days = [datetime(2024, 6, 1, 9), datetime(2024, 6, 1, 20), datetime(2024, 6, 2, 8)]
        assert listening_streaks(days)["longest"] == 2

    def test_empty_is_zero(self) -> None:
        result = listening_streaks([])
        assert result["longest"] == 0
        assert result["current"] == 0


class TestRhythmReport:
    def test_assembles_all_sections(self) -> None:
        plays = [
            _play(1, datetime(2024, 6, 1, 9), ms=200_000),
            _play(1, datetime(2024, 6, 2, 9), ms=200_000),
            _play(2, datetime(2024, 6, 2, 10), ms=200_000),
        ]
        meta = {1: {"name": "Alpha", "artist": "A"}, 2: {"name": "Beta", "artist": "B"}}
        report = rhythm_report(plays, track_meta=meta)
        assert report["total_plays"] == 3
        assert report["distinct_tracks"] == 2
        # Reuses I2 listening_clock shape.
        assert report["clock"]["peak_hour"] == 9
        assert len(report["clock"]["hours"]) == 24
        assert report["minutes"]["minutes"] > 0
        assert report["streaks"]["longest"] == 2
        # Top played, most-played first, with resolved names.
        assert report["top_played"][0]["track_id"] == 1
        assert report["top_played"][0]["plays"] == 2
        assert report["top_played"][0]["name"] == "Alpha"

    def test_empty_library_is_zero_shaped(self) -> None:
        report = rhythm_report([], track_meta={})
        assert report["total_plays"] == 0
        assert report["distinct_tracks"] == 0
        assert report["clock"]["peak_hour"] is None
        assert report["top_played"] == []
        assert report["streaks"]["longest"] == 0
