"""Temporal analytics: how the library's sound and size move by quarter.

Inputs are add records — one per (playlist, track) membership with the time
the track was added and the track's percentile centroid. A track added to
several playlists counts once per playlist: taste drift follows curation
activity, and each add was a curation decision.
"""

from dataclasses import dataclass
from datetime import datetime

# Drift tracks the three features the dashboard charts.
DRIFT_FEATURES = ("energy", "valence", "acousticness")


@dataclass(frozen=True)
class AddRecord:
    playlist_id: int
    track_id: int
    added_at: datetime | None
    # Percentile ranks for DRIFT_FEATURES; None when the track has no features.
    centroid: dict[str, float] | None


@dataclass(frozen=True)
class DriftPoint:
    quarter: str
    energy: float
    valence: float
    acousticness: float


@dataclass(frozen=True)
class GrowthPoint:
    quarter: str
    track_count: int


@dataclass(frozen=True)
class GrowthCurve:
    playlist_id: int
    points: list[GrowthPoint]


def quarter_of(moment: datetime) -> str:
    """Calendar quarter label, e.g. 2026Q3."""
    return f"{moment.year}Q{(moment.month - 1) // 3 + 1}"


def _quarter_range(quarters: set[str]) -> list[str]:
    """Every quarter from the earliest to the latest seen, inclusive."""
    if not quarters:
        return []
    parsed = sorted((int(q[:4]), int(q[5])) for q in quarters)
    (start_year, start_q), (end_year, end_q) = parsed[0], parsed[-1]
    labels: list[str] = []
    year, quarter = start_year, start_q
    while (year, quarter) <= (end_year, end_q):
        labels.append(f"{year}Q{quarter}")
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
    return labels


def drift_by_quarter(records: list[AddRecord]) -> list[DriftPoint]:
    """Mean add-centroid per quarter, oldest first.

    Quarters with no enriched adds are skipped — an absent point is honest,
    an interpolated one would invent taste.
    """
    buckets: dict[str, list[dict[str, float]]] = {}
    for record in records:
        if record.added_at is None or record.centroid is None:
            continue
        buckets.setdefault(quarter_of(record.added_at), []).append(record.centroid)

    points: list[DriftPoint] = []
    for quarter in sorted(buckets):
        centroids = buckets[quarter]
        means = {
            feature: sum(c[feature] for c in centroids) / len(centroids)
            for feature in DRIFT_FEATURES
        }
        points.append(DriftPoint(quarter=quarter, **means))
    return points


def growth_curves(records: list[AddRecord]) -> list[GrowthCurve]:
    """Cumulative track count per playlist per quarter.

    All curves share the same quarter axis (earliest to latest add anywhere)
    so they chart together without client-side alignment.
    """
    dated = [r for r in records if r.added_at is not None]
    axis = _quarter_range({quarter_of(r.added_at) for r in dated if r.added_at})
    if not axis:
        return []

    adds: dict[int, dict[str, int]] = {}
    for record in dated:
        assert record.added_at is not None
        per_quarter = adds.setdefault(record.playlist_id, {})
        quarter = quarter_of(record.added_at)
        per_quarter[quarter] = per_quarter.get(quarter, 0) + 1

    curves: list[GrowthCurve] = []
    for playlist_id in sorted(adds):
        running = 0
        points: list[GrowthPoint] = []
        for quarter in axis:
            running += adds[playlist_id].get(quarter, 0)
            points.append(GrowthPoint(quarter=quarter, track_count=running))
        curves.append(GrowthCurve(playlist_id=playlist_id, points=points))
    return curves
