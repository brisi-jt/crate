"""Percentile-space transform.

Every analytics metric compares tracks by their rank within the library, not
by raw feature values. Rank uses the mean-rank convention so ties land midway:
rank(x) = (#below + 0.5 * #equal) / n, giving values in [0, 1].
"""

from bisect import bisect_left, bisect_right

import numpy as np

# Rank assigned when a track is missing a value for a feature: the library
# median, so the gap neither attracts nor repels distance metrics.
NEUTRAL_RANK = 0.5


def percentile_rank(sorted_values: list[float], x: float) -> float:
    """Rank of x within sorted_values (ascending), mean-rank tie handling."""
    n = len(sorted_values)
    if n == 0:
        return NEUTRAL_RANK
    below = bisect_left(sorted_values, x)
    equal = bisect_right(sorted_values, x) - below
    return (below + 0.5 * equal) / n


class PercentileSpace:
    """Maps raw feature dicts to percentile vectors against library distributions.

    Feature order is fixed at construction (insertion order of the library
    dict), so matrices built from the same space are column-compatible.
    """

    def __init__(self, library: dict[str, list[float]]) -> None:
        self._sorted: dict[str, list[float]] = {
            feature: sorted(values) for feature, values in library.items()
        }
        self.features: tuple[str, ...] = tuple(self._sorted)

    def transform(self, values: dict[str, float | None]) -> dict[str, float]:
        """Percentile vector for one track; missing values take the neutral rank."""
        vector: dict[str, float] = {}
        for feature in self.features:
            value = values.get(feature)
            if value is None:
                vector[feature] = NEUTRAL_RANK
            else:
                vector[feature] = percentile_rank(self._sorted[feature], value)
        return vector

    def matrix(self, rows: list[dict[str, float | None]]) -> np.ndarray:
        """(n_tracks, n_features) percentile matrix, rows in input order."""
        data = [[self.transform(row)[feature] for feature in self.features] for row in rows]
        return np.array(data, dtype=float).reshape(len(rows), len(self.features))
