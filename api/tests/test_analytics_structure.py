"""Structure metrics: overlap, subsets, duplicates, cohesion, outliers.

Every expected number here is hand-computed from the micro-fixture so a
regression in any formula fails loudly against a value a human can re-derive.
"""

import math

import numpy as np
import pytest

from crate.services.analytics.structure import (
    SUBSET_CONTAINMENT,
    cohesion,
    containment,
    find_duplicate_groups,
    jaccard,
    outliers,
    overlap_edges,
)

pytestmark = pytest.mark.unit


class TestSetMetrics:
    def test_jaccard_hand_computed(self) -> None:
        # A={1,2,3,4}, B={3,4,5}: shared 2, union 5
        assert jaccard({1, 2, 3, 4}, {3, 4, 5}) == pytest.approx(2 / 5)

    def test_containment_hand_computed(self) -> None:
        # shared 2 over the smaller set (3 tracks)
        assert containment({1, 2, 3, 4}, {3, 4, 5}) == pytest.approx(2 / 3)

    def test_full_subset_has_containment_one(self) -> None:
        assert containment({1, 2}, {1, 2, 3}) == pytest.approx(1.0)

    def test_empty_sets_are_zero_not_errors(self) -> None:
        assert jaccard(set(), {1}) == 0.0
        assert containment(set(), {1}) == 0.0
        assert jaccard(set(), set()) == 0.0


class TestOverlapEdges:
    def test_edges_carry_shared_count_jaccard_and_subset_flag(self) -> None:
        memberships = {
            1: {10, 11, 12, 13},  # A
            2: {12, 13, 14},  # B — shares {12,13} with A
            3: {10, 11, 12, 13, 14, 15},  # C — superset of A and of B
        }
        edges = {(e.source, e.target): e for e in overlap_edges(memberships)}

        ab = edges[(1, 2)]
        assert ab.shared == 2
        assert ab.jaccard == pytest.approx(2 / 5)
        assert ab.containment == pytest.approx(2 / 3)
        assert not ab.subset

        ac = edges[(1, 3)]
        assert ac.shared == 4
        assert ac.containment == pytest.approx(1.0)
        assert ac.subset

        bc = edges[(2, 3)]
        assert bc.shared == 3
        assert bc.containment == pytest.approx(1.0)
        assert bc.subset

    def test_disjoint_playlists_produce_no_edge(self) -> None:
        assert overlap_edges({1: {1, 2}, 2: {3, 4}}) == []

    def test_subset_threshold_is_ninety_percent(self) -> None:
        assert pytest.approx(0.9) == SUBSET_CONTAINMENT
        # 9 of 10 tracks contained: right at the threshold
        small = set(range(9)) | {99}
        big = set(range(20))
        edges = overlap_edges({1: small, 2: big})
        assert edges[0].containment == pytest.approx(0.9)
        assert edges[0].subset


class TestDuplicates:
    def test_same_isrc_different_spotify_ids_grouped(self) -> None:
        tracks = [
            {"track_id": 1, "spotify_id": "sp1", "isrc": "US1", "name": "One", "artist": "A"},
            {
                "track_id": 2,
                "spotify_id": "sp2",
                "isrc": "US1",
                "name": "One (Remaster)",
                "artist": "A",
            },
            {"track_id": 3, "spotify_id": "sp3", "isrc": "US3", "name": "Other", "artist": "B"},
        ]
        memberships = {1: {1, 3}, 2: {2}}
        names = {1: "Alpha", 2: "Beta"}
        groups = find_duplicate_groups(tracks, memberships, names)
        assert len(groups) == 1
        group = groups[0]
        assert group.isrc == "US1"
        assert sorted(group.playlists) == ["Alpha", "Beta"]

    def test_exact_track_repeated_in_one_playlist_is_reported(self) -> None:
        tracks = [
            {"track_id": 1, "spotify_id": "sp1", "isrc": None, "name": "One", "artist": "A"},
        ]
        # Same track id occupies two positions in playlist 1.
        occurrences = {1: [1, 1]}
        groups = find_duplicate_groups(tracks, {1: {1}}, {1: "Alpha"}, occurrences=occurrences)
        assert len(groups) == 1
        assert groups[0].playlists == ["Alpha"]

    def test_track_in_two_playlists_is_not_a_duplicate(self) -> None:
        tracks = [
            {"track_id": 1, "spotify_id": "sp1", "isrc": "US1", "name": "One", "artist": "A"},
        ]
        groups = find_duplicate_groups(tracks, {1: {1}, 2: {1}}, {1: "Alpha", 2: "Beta"})
        assert groups == []


class TestCohesion:
    def test_two_opposite_corners_of_percentile_space(self) -> None:
        # distance sqrt(2), normalized by sqrt(d=2) -> 1.0
        vectors = np.array([[0.0, 0.0], [1.0, 1.0]])
        assert cohesion(vectors) == pytest.approx(1.0)

    def test_identical_tracks_have_zero_distance(self) -> None:
        vectors = np.array([[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]])
        assert cohesion(vectors) == pytest.approx(0.0)

    def test_three_track_hand_computation(self) -> None:
        # pairs: (0,0)-(0,1)=1, (0,0)-(1,0)=1, (0,1)-(1,0)=sqrt(2)
        # mean = (2 + sqrt(2))/3, normalized by sqrt(2)
        vectors = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
        expected = ((2 + math.sqrt(2)) / 3) / math.sqrt(2)
        assert cohesion(vectors) == pytest.approx(expected)

    def test_fewer_than_two_tracks_is_none(self) -> None:
        assert cohesion(np.array([[0.5, 0.5]])) is None
        assert cohesion(np.empty((0, 2))) is None


class TestOutliers:
    def test_mahalanobis_with_diagonal_covariance_hand_computed(self) -> None:
        # Corners of a square + two center points. Sample covariance is
        # diag(3.2, 3.2), zero cross-term, so the corner distance is
        # sqrt(4/3.2 + 4/3.2) = sqrt(2.5) = 1.5811...
        vectors = np.array(
            [
                [0.0, 0.0],
                [0.0, 4.0],
                [4.0, 0.0],
                [4.0, 4.0],
                [2.0, 2.0],
                [2.0, 2.0],
            ]
        )
        track_ids = [1, 2, 3, 4, 5, 6]
        result = outliers(vectors, track_ids, top_n=4)
        assert result.method == "mahalanobis"
        assert [entry.track_id for entry in result.entries] == [1, 2, 3, 4]
        for entry in result.entries:
            assert entry.distance == pytest.approx(math.sqrt(2.5))

    def test_singular_covariance_falls_back_to_euclidean(self) -> None:
        # 3 points in 9 dimensions: covariance rank <= 2, always singular.
        vectors = np.array(
            [
                [0.5] * 9,
                [0.5] * 9,
                [0.9] * 9,
            ]
        )
        result = outliers(vectors, [1, 2, 3], top_n=1)
        assert result.method == "euclidean"
        assert result.entries[0].track_id == 3
        # centroid is (0.6333..)*9; distance = sqrt(9 * (0.9-0.63333)^2) = 0.8
        assert result.entries[0].distance == pytest.approx(0.8, abs=1e-6)

    def test_fewer_than_three_tracks_yields_no_outliers(self) -> None:
        result = outliers(np.array([[0.1], [0.9]]), [1, 2], top_n=5)
        assert result.entries == []

    def test_ties_break_on_track_id_for_determinism(self) -> None:
        vectors = np.array([[0.0], [1.0], [0.5], [0.5]])
        result = outliers(vectors, [7, 3, 1, 2], top_n=2)
        assert [entry.track_id for entry in result.entries] == [3, 7]
