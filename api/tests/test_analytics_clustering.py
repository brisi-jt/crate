"""Track map: seeded UMAP projection, HDBSCAN clusters, ARI, split/merge.

The fixture is two well-separated blobs in 9-dimensional percentile space, so
cluster recovery is unambiguous and the ARI against matching playlists is
exactly 1.0.
"""

import numpy as np
import pytest

from crate.services.analytics.clustering import compute_track_map

pytestmark = pytest.mark.unit


def two_blob_fixture() -> tuple[np.ndarray, list[int], dict[int, set[int]]]:
    """40 tracks: ids 1-20 hug 0.15, ids 21-40 hug 0.85."""
    rng = np.random.default_rng(7)
    low = 0.15 + rng.normal(0, 0.02, size=(20, 9))
    high = 0.85 + rng.normal(0, 0.02, size=(20, 9))
    matrix = np.clip(np.vstack([low, high]), 0.0, 1.0)
    track_ids = list(range(1, 41))
    memberships = {1: set(range(1, 21)), 2: set(range(21, 41))}
    return matrix, track_ids, memberships


class TestTrackMap:
    def test_recovers_two_clusters_with_perfect_ari(self) -> None:
        matrix, track_ids, memberships = two_blob_fixture()
        result = compute_track_map(matrix, track_ids, memberships)
        assert result is not None
        assert result.cluster_count == 2
        assert result.ari == pytest.approx(1.0)
        assert len(result.points) == 40
        # Every point carries 2D coordinates.
        for point in result.points:
            assert isinstance(point.x, float) and isinstance(point.y, float)

    def test_seeded_umap_is_deterministic(self) -> None:
        matrix, track_ids, memberships = two_blob_fixture()
        first = compute_track_map(matrix, track_ids, memberships)
        second = compute_track_map(matrix, track_ids, memberships)
        assert first is not None and second is not None
        assert first.layout_hash == second.layout_hash
        assert first.layout_hash  # non-empty sha256 hex

    def test_playlist_spanning_two_clusters_gets_split_suggestion(self) -> None:
        matrix, track_ids, _ = two_blob_fixture()
        # One playlist straddles both blobs.
        memberships = {3: set(range(1, 41))}
        result = compute_track_map(matrix, track_ids, memberships)
        assert result is not None
        assert [s.playlist_id for s in result.split_suggestions] == [3]
        assert len(result.split_suggestions[0].clusters) == 2

    def test_two_playlists_in_one_cluster_get_merge_suggestion(self) -> None:
        matrix, track_ids, _ = two_blob_fixture()
        # Both playlists live entirely inside the low blob; playlist 6 owns
        # the high blob alone so it must not appear in any merge.
        memberships = {
            4: set(range(1, 11)),
            5: set(range(11, 21)),
            6: set(range(21, 41)),
        }
        result = compute_track_map(matrix, track_ids, memberships)
        assert result is not None
        assert len(result.merge_suggestions) == 1
        assert sorted(result.merge_suggestions[0].playlist_ids) == [4, 5]

    def test_cohesive_playlists_produce_no_suggestions(self) -> None:
        matrix, track_ids, memberships = two_blob_fixture()
        result = compute_track_map(matrix, track_ids, memberships)
        assert result is not None
        assert result.split_suggestions == []
        assert result.merge_suggestions == []

    def test_too_few_tracks_returns_none(self) -> None:
        matrix = np.full((3, 9), 0.5)
        assert compute_track_map(matrix, [1, 2, 3], {1: {1, 2, 3}}) is None
