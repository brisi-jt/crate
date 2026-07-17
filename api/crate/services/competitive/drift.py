"""F5 — taste drift: fingerprint math for now-vs-past-self comparisons.

A fingerprint is the mean percentile vector of a set of tracks over the drift
features. The comparison is the per-axis delta (now minus then) plus a single
Euclidean distance summarising how far taste has moved and which axis moved most.

Pure over already-transformed percentile vectors; the engine builds the
"then" fingerprint from a ``TopItemsSnapshot`` and the "now" fingerprint from
the current library.
"""

from math import sqrt
from typing import Any


def fingerprint_of(
    track_ids: list[int],
    vectors: dict[int, dict[str, float]],
    features: tuple[str, ...],
) -> dict[str, float] | None:
    """Mean percentile vector over the enriched tracks in ``track_ids``.

    Tracks with no vector (unenriched, or not in the catalog) are skipped.
    None when none of the ids resolve to a vector.
    """
    present = [vectors[tid] for tid in track_ids if tid in vectors]
    if not present:
        return None
    return {
        feature: round(sum(v[feature] for v in present) / len(present), 4) for feature in features
    }


def fingerprint_delta(
    now: dict[str, float] | None,
    then: dict[str, float] | None,
    features: tuple[str, ...],
) -> dict[str, Any] | None:
    """Per-axis drift (now - then) plus overall distance and the biggest mover.

    None when either fingerprint is unavailable (nothing to compare).
    """
    if now is None or then is None:
        return None
    axes = [
        {
            "feature": feature,
            "now": now[feature],
            "then": then[feature],
            "delta": round(now[feature] - then[feature], 4),
        }
        for feature in features
    ]
    distance = sqrt(sum((a["delta"]) ** 2 for a in axes))
    biggest = max(axes, key=lambda a: abs(a["delta"]))
    return {
        "axes": axes,
        "distance": round(distance, 4),
        "biggest_mover": {"feature": biggest["feature"], "delta": biggest["delta"]},
    }
