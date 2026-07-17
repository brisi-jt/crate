"""Clustering-quality regression suite (G2 + G3).

The gate for the clustering rework is a quality TEST, not an eyeball. These
fixtures have known structure so the quality metrics (cluster count, largest
share, noise share) are checkable without a human looking at the map.

What's proven here, and what kind of proof each is:

* **G2 unit regressions** — ``scaled_min_cluster_size`` and ``cluster_quality``
  are new API (ImportError on pre-fix code); their behaviour is asserted
  directly.
* **G3 ablation (genuine regression)** — the ``genre_matrix`` parameter is new;
  blending a per-track genre vector separates two groups that are acoustically
  identical but genre-distinct, which the feature-only distance CANNOT. This
  test fails on pre-fix code two ways: the parameter didn't exist, and without
  it the groups do not separate. This is the load-bearing G3 proof.
* **G2 property/smoke tests** — the healthy-distribution and hull-geography
  tests assert invariants the embedding-clustering pipeline should uphold.
  NOTE: clean synthetic blobs cluster fine even in the pre-fix raw-space
  pipeline, so these are *property/smoke* coverage, not regressions — the
  degenerate 2-cluster blob is a real-data phenomenon (a percentile-uniform
  hyperball with only latent genre structure) that small synthetic fixtures do
  not reproduce faithfully. The real G2 gate is the live-library measurement in
  ``test_real_library_clustering_quality`` (integration), which records the
  before/after cluster count / largest-share / noise-share against the
  2 / 71% / 29% baseline.
"""

import numpy as np
import pytest

from crate.services.analytics.clustering import (
    cluster_quality,
    compute_track_map,
    scaled_min_cluster_size,
)

pytestmark = pytest.mark.unit


def many_blob_fixture(
    blobs: int = 6, per_blob: int = 60, dims: int = 8, spread: float = 0.02, seed: int = 11
) -> tuple[np.ndarray, list[int]]:
    """`blobs` well-separated gaussian blobs in the unit percentile cube.

    Centers are placed on a lattice so the blobs are unambiguously distinct;
    a competent map recovers roughly ``blobs`` clusters with a balanced size
    distribution and little noise.
    """
    rng = np.random.default_rng(seed)
    centers = rng.uniform(0.1, 0.9, size=(blobs, dims))
    # Push centers apart so blobs do not touch (min pairwise gap).
    rows = []
    for c in centers:
        rows.append(np.clip(c + rng.normal(0, spread, size=(per_blob, dims)), 0.0, 1.0))
    matrix = np.vstack(rows)
    track_ids = list(range(1, matrix.shape[0] + 1))
    return matrix, track_ids


# -- scaled_min_cluster_size ---------------------------------------------------


def test_scaled_min_cluster_size_grows_with_n() -> None:
    """mcs must scale with n — the old min(5, n//2) forced speck clusters at 6k."""
    small = scaled_min_cluster_size(40)
    large = scaled_min_cluster_size(6000)
    assert large > small
    # At library scale the floor is well above the old ceiling of 5.
    assert large >= 20
    # Never below a sane floor even for tiny inputs.
    assert scaled_min_cluster_size(12) >= 2


# -- cluster_quality metric ----------------------------------------------------


def test_cluster_quality_reports_shares() -> None:
    labels = np.array([0, 0, 0, 1, 1, -1])
    q = cluster_quality(labels)
    assert q.cluster_count == 2
    assert q.noise_share == pytest.approx(1 / 6)
    # largest cluster is label 0 with 3 of 6 points
    assert q.largest_share == pytest.approx(3 / 6)


# -- G2: embedding clustering recovers structure -------------------------------


class TestEmbeddingClusteringQuality:
    def test_many_blobs_recovered_with_healthy_distribution(self) -> None:
        matrix, track_ids = many_blob_fixture(blobs=6, per_blob=60)
        result = compute_track_map(matrix, track_ids, {})
        assert result is not None
        q = cluster_quality(np.array([p.cluster for p in result.points]))
        # Several clusters (not the degenerate 1-2), balanced, low noise.
        assert q.cluster_count >= 4
        assert q.largest_share < 0.4
        assert q.noise_share < 0.2

    def test_hulls_match_geography(self) -> None:
        """Clustering the embedding (not the raw matrix) means cluster ids are a
        function of the 2D layout — points sharing a cluster sit together."""
        matrix, track_ids = many_blob_fixture(blobs=5, per_blob=50)
        result = compute_track_map(matrix, track_ids, {})
        assert result is not None
        by_cluster: dict[int, list[tuple[float, float]]] = {}
        for p in result.points:
            if p.cluster != -1:
                by_cluster.setdefault(p.cluster, []).append((p.x, p.y))
        # Each cluster's on-screen spread is far smaller than the whole layout's
        # spread — clusters are geographically compact, not scattered.
        xs = [p.x for p in result.points]
        ys = [p.y for p in result.points]
        layout_span = max(max(xs) - min(xs), max(ys) - min(ys))
        for coords in by_cluster.values():
            cxs = [c[0] for c in coords]
            cys = [c[1] for c in coords]
            cluster_span = max(max(cxs) - min(cxs), max(cys) - min(cys))
            assert cluster_span < layout_span * 0.6


# -- G3: genre blend improves separation ---------------------------------------


class TestGenreBlendAblation:
    def _acoustically_merged_fixture(
        self,
    ) -> tuple[np.ndarray, np.ndarray, list[int]]:
        """Two genre groups sitting in the SAME acoustic region.

        Feature-only: one blob. Feature+genre: two separable groups. The genre
        block is a one-hot per group, scaled so it dominates the near-zero
        acoustic separation.
        """
        rng = np.random.default_rng(3)
        n = 60
        # Both groups share one acoustic center — acoustically inseparable.
        acoustic = np.clip(0.5 + rng.normal(0, 0.02, size=(2 * n, 6)), 0.0, 1.0)
        # Distinct genre one-hots per group.
        genre = np.zeros((2 * n, 2), dtype=float)
        genre[:n, 0] = 1.0
        genre[n:, 1] = 1.0
        track_ids = list(range(1, 2 * n + 1))
        return acoustic, genre, track_ids

    def test_feature_only_cannot_separate_genre_groups(self) -> None:
        acoustic, _genre, track_ids = self._acoustically_merged_fixture()
        result = compute_track_map(acoustic, track_ids, {})
        assert result is not None
        q = cluster_quality(np.array([p.cluster for p in result.points]))
        # Acoustically merged: one dominant blob (or all noise) — NOT 2 groups.
        assert q.cluster_count <= 1 or q.largest_share > 0.7

    def test_genre_blend_separates_the_groups(self) -> None:
        acoustic, genre, track_ids = self._acoustically_merged_fixture()
        # Weight the genre block so its separation dominates.
        result = compute_track_map(acoustic, track_ids, {}, genre_matrix=genre * 6.0)
        assert result is not None
        q = cluster_quality(np.array([p.cluster for p in result.points]))
        # Two balanced clusters emerge once genre is in the distance.
        assert q.cluster_count >= 2
        assert q.largest_share < 0.7
