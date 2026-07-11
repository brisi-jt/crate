"""Percentile-space transform — the foundation every analytics metric stands on.

Feature values are Essentia-distributed, so analytics never compare raw
values; everything is ranked against the library's own distribution first.
Rank definition (mean rank): rank(x) = (#below + 0.5 * #equal) / n.
"""

import pytest

from crate.services.analytics.percentiles import PercentileSpace, percentile_rank

pytestmark = pytest.mark.unit


class TestPercentileRank:
    def test_rank_of_smallest_value(self) -> None:
        # library [1,2,3,4]: rank(1) = (0 + 0.5*1)/4 = 0.125
        assert percentile_rank([1.0, 2.0, 3.0, 4.0], 1.0) == pytest.approx(0.125)

    def test_rank_of_largest_value(self) -> None:
        # rank(4) = (3 + 0.5)/4 = 0.875
        assert percentile_rank([1.0, 2.0, 3.0, 4.0], 4.0) == pytest.approx(0.875)

    def test_rank_of_value_between_samples(self) -> None:
        # rank(2.5) = (2 + 0)/4 = 0.5
        assert percentile_rank([1.0, 2.0, 3.0, 4.0], 2.5) == pytest.approx(0.5)

    def test_rank_below_all_is_zero(self) -> None:
        assert percentile_rank([1.0, 2.0, 3.0, 4.0], 0.0) == 0.0

    def test_rank_above_all_is_one(self) -> None:
        assert percentile_rank([1.0, 2.0, 3.0, 4.0], 5.0) == 1.0

    def test_ties_share_the_mean_rank(self) -> None:
        # library [1,2,2,3]: rank(2) = (1 + 0.5*2)/4 = 0.5
        assert percentile_rank([1.0, 2.0, 2.0, 3.0], 2.0) == pytest.approx(0.5)

    def test_single_value_library(self) -> None:
        assert percentile_rank([3.0], 3.0) == pytest.approx(0.5)


class TestPercentileSpace:
    def test_transform_ranks_each_feature_against_its_library(self) -> None:
        space = PercentileSpace(
            {"energy": [0.1, 0.2, 0.3, 0.4], "tempo": [100.0, 120.0, 140.0, 160.0]}
        )
        vector = space.transform({"energy": 0.1, "tempo": 160.0})
        assert vector["energy"] == pytest.approx(0.125)
        assert vector["tempo"] == pytest.approx(0.875)

    def test_missing_feature_value_imputes_median_rank(self) -> None:
        space = PercentileSpace({"energy": [0.1, 0.2, 0.3, 0.4]})
        vector = space.transform({"energy": None})
        assert vector["energy"] == pytest.approx(0.5)

    def test_feature_order_is_stable(self) -> None:
        space = PercentileSpace({"energy": [1.0], "valence": [1.0]})
        assert space.features == ("energy", "valence")

    def test_matrix_rows_follow_input_order(self) -> None:
        space = PercentileSpace({"energy": [0.0, 1.0]})
        matrix = space.matrix([{"energy": 0.0}, {"energy": 1.0}])
        assert matrix.shape == (2, 1)
        assert matrix[0, 0] == pytest.approx(0.25)
        assert matrix[1, 0] == pytest.approx(0.75)
