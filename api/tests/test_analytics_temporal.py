"""Temporal analytics: quarterly add-centroid drift and playlist growth curves."""

from datetime import datetime

import pytest

from crate.services.analytics.temporal import AddRecord, drift_by_quarter, growth_curves, quarter_of

pytestmark = pytest.mark.unit


def record(
    added_at: datetime,
    playlist_id: int = 1,
    track_id: int = 1,
    centroid: dict[str, float] | None = None,
) -> AddRecord:
    return AddRecord(
        playlist_id=playlist_id,
        track_id=track_id,
        added_at=added_at,
        centroid=centroid,
    )


class TestQuarterOf:
    def test_quarter_boundaries(self) -> None:
        assert quarter_of(datetime(2025, 1, 1)) == "2025Q1"
        assert quarter_of(datetime(2025, 3, 31)) == "2025Q1"
        assert quarter_of(datetime(2025, 4, 1)) == "2025Q2"
        assert quarter_of(datetime(2025, 12, 31)) == "2025Q4"


class TestDrift:
    def test_quarterly_centroid_is_mean_of_adds_in_that_quarter(self) -> None:
        records = [
            record(
                datetime(2025, 1, 10),
                track_id=1,
                centroid={"energy": 0.2, "valence": 0.4, "acousticness": 0.6},
            ),
            record(
                datetime(2025, 2, 20),
                track_id=2,
                centroid={"energy": 0.4, "valence": 0.6, "acousticness": 0.8},
            ),
            record(
                datetime(2025, 7, 1),
                track_id=3,
                centroid={"energy": 0.9, "valence": 0.1, "acousticness": 0.5},
            ),
        ]
        drift = drift_by_quarter(records)
        assert [point.quarter for point in drift] == ["2025Q1", "2025Q3"]
        q1 = drift[0]
        assert q1.energy == pytest.approx(0.3)
        assert q1.valence == pytest.approx(0.5)
        assert q1.acousticness == pytest.approx(0.7)
        q3 = drift[1]
        assert q3.energy == pytest.approx(0.9)

    def test_adds_without_features_are_excluded_from_drift(self) -> None:
        records = [
            record(datetime(2025, 1, 10), track_id=1, centroid=None),
            record(
                datetime(2025, 1, 12),
                track_id=2,
                centroid={"energy": 1.0, "valence": 1.0, "acousticness": 1.0},
            ),
        ]
        drift = drift_by_quarter(records)
        assert len(drift) == 1
        assert drift[0].energy == pytest.approx(1.0)

    def test_no_records_means_empty_drift(self) -> None:
        assert drift_by_quarter([]) == []


class TestGrowth:
    def test_cumulative_counts_per_playlist_per_quarter(self) -> None:
        records = [
            record(datetime(2025, 1, 5), playlist_id=1, track_id=1),
            record(datetime(2025, 1, 6), playlist_id=1, track_id=2),
            record(datetime(2025, 7, 1), playlist_id=1, track_id=3),
            record(datetime(2025, 7, 2), playlist_id=2, track_id=4),
        ]
        curves = growth_curves(records)
        by_playlist = {curve.playlist_id: curve for curve in curves}

        # Playlist 1: 2 adds in Q1, 1 in Q3 -> cumulative 2 then 3. The
        # quiet Q2 still appears so curves share a common quarter axis.
        assert [(p.quarter, p.track_count) for p in by_playlist[1].points] == [
            ("2025Q1", 2),
            ("2025Q2", 2),
            ("2025Q3", 3),
        ]
        # Playlist 2 had nothing until Q3.
        assert [(p.quarter, p.track_count) for p in by_playlist[2].points] == [
            ("2025Q1", 0),
            ("2025Q2", 0),
            ("2025Q3", 1),
        ]

    def test_adds_without_timestamp_are_ignored(self) -> None:
        records = [
            AddRecord(playlist_id=1, track_id=1, added_at=None, centroid=None),
            record(datetime(2025, 1, 5), playlist_id=1, track_id=2),
        ]
        curves = growth_curves(records)
        assert curves[0].points[-1].track_count == 1
