"""Track map: seeded UMAP 2D projection + HDBSCAN clusters vs playlists.

UMAP runs with a fixed random_state (which forces single-threaded, exactly
reproducible layouts), so the same library always produces the same map. The
single-threaded cost is why the map is precomputed into an AnalyticsSnapshot
and never computed in the request path (M1) — the answer to UMAP's cost is
caching, not parallelism (dropping the seed for `n_jobs>1` would make the
layout non-reproducible). HDBSCAN comes from scikit-learn — no separate hdbscan
package.

**Two embeddings.** The layout you *see* and the geometry we *cluster* are
different jobs:

* the **display embedding** (min_dist=0.1) spaces points out prettily for the
  on-screen x/y;
* the **clustering embedding** (n_neighbors=30, min_dist=0.0 — the standard
  "UMAP-for-clustering" recipe) packs each dense region tight so HDBSCAN can
  find density valleys.

HDBSCAN runs on the *clustering* embedding, and its labels are painted onto the
*display* layout. Clustering the embedding (not the raw 9-D percentile matrix,
which is a single dense hyperball with no density valleys) is what turns the
degenerate 2-cluster blob into a usable ~15-30 cluster structure, and it also
fixes the correctness bug where hulls drawn on the display layout disagreed with
cluster ids computed in raw space.

**Genre in the distance.** Percentile acoustics alone make clusters that
are hard to read ("this corner is… mid-energy?"). The caller can pass a
pre-weighted per-track ``genre_matrix`` (a reduced genre profile from the ENAO
``ArtistGenre`` join); it is concatenated onto the acoustic block before UMAP so
genre-distinct groups separate even when their acoustics overlap. Genre is the
single strongest *semantic* signal we have.

**Loudness excluded (M3, decorrelation).** Measured on the real owned library,
loudness ranks correlate with energy ranks at r=0.72 — loudness is very nearly a
duplicate energy axis, so including both lets "energy" count ~1.7x in the
euclidean distance, lowering the effective rank of the space and blurring
cluster structure. Loudness is still calibrated, stored, and used for
display/color; only the clustering matrix drops it. See ``clustering_features``.
"""

import hashlib
from dataclasses import dataclass

import numpy as np

UMAP_SEED = 42

# Display embedding: the on-screen x/y. min_dist spaces points for legibility.
DISPLAY_MIN_DIST = 0.1
DISPLAY_NEIGHBORS = 15

# Clustering embedding: the geometry HDBSCAN sees. The standard
# UMAP-for-clustering recipe — more neighbours for global structure, min_dist=0
# so each dense region collapses to a point HDBSCAN can find.
CLUSTER_MIN_DIST = 0.0
CLUSTER_NEIGHBORS = 30

MIN_TRACKS_FOR_MAP = 10

# HDBSCAN min_cluster_size scales with n. The old min(5, n//2) forced
# speck clusters at library scale (~6k tracks) — a 7-track dust cluster amid a
# 71% blob. These anchor a linear scale between a small-library floor and a
# proportional ceiling.
MIN_CLUSTER_FLOOR = 2
MIN_CLUSTER_DIVISOR = 200  # ~1 required member per 200 tracks
MIN_CLUSTER_CEIL_FLOOR = 20  # once past this many tracks, never below 20


def scaled_min_cluster_size(n: int) -> int:
    """HDBSCAN ``min_cluster_size`` for ``n`` tracks.

    Scales with n so clusters are meaningful at library scale without vanishing
    on a tiny fixture: ``max(n // 200, 20)`` once the library is large, but never
    above ``n // 2`` and never below 2 for very small inputs.
    """
    if n < 2 * MIN_CLUSTER_FLOOR:
        return MIN_CLUSTER_FLOOR
    proportional = n // MIN_CLUSTER_DIVISOR
    scaled = max(proportional, MIN_CLUSTER_CEIL_FLOOR)
    # Never demand more members than half the population could supply.
    return max(MIN_CLUSTER_FLOOR, min(scaled, n // 2))


# Features dropped from the clustering distance metric (M3). Loudness ~ energy
# at r=0.72 on the real library, so it double-counts energy; kept for display.
CLUSTERING_EXCLUDED_FEATURES = ("loudness",)


def clustering_features(features: tuple[str, ...]) -> tuple[str, ...]:
    """The feature list to cluster on: ``features`` minus the decorrelated ones.

    Preserves order and every non-excluded feature, so the caller can build a
    column-aligned matrix.
    """
    return tuple(f for f in features if f not in CLUSTERING_EXCLUDED_FEATURES)


# A playlist is a split candidate when >= 2 clusters each hold this share of
# its clustered tracks (and at least SPLIT_MIN_MEMBERS tracks). This is a small
# constant floor on evidence, independent of the (n-scaled) HDBSCAN mcs — a
# playlist that puts 6 tracks each in two clusters is a real split even when the
# library-wide mcs is 30.
SPLIT_MIN_SHARE = 0.3
SPLIT_MIN_MEMBERS = 5
# Playlists whose dominant cluster holds this share of their clustered tracks
# are merge candidates when they share that dominant cluster.
MERGE_DOMINANT_SHARE = 0.6


@dataclass(frozen=True)
class ClusterQuality:
    """The gate numbers for the clustering rework (target: 15-30 clusters,
    largest < 25%, noise < 15% on the owned library; baseline was 2/71%/29%)."""

    cluster_count: int
    largest_share: float
    noise_share: float


def cluster_quality(labels: np.ndarray) -> ClusterQuality:
    """Quality metrics over HDBSCAN labels (-1 = noise)."""
    labels = np.asarray(labels)
    total = int(labels.shape[0]) if labels.size else 0
    if total == 0:
        return ClusterQuality(cluster_count=0, largest_share=0.0, noise_share=0.0)
    noise = int((labels == -1).sum())
    non_noise = labels[labels != -1]
    if non_noise.size == 0:
        return ClusterQuality(cluster_count=0, largest_share=0.0, noise_share=noise / total)
    _, counts = np.unique(non_noise, return_counts=True)
    return ClusterQuality(
        cluster_count=int(counts.shape[0]),
        largest_share=float(counts.max()) / total,
        noise_share=noise / total,
    )


@dataclass(frozen=True)
class MapPoint:
    track_id: int
    x: float
    y: float
    # HDBSCAN cluster label; -1 marks noise (no dense neighbourhood).
    cluster: int


@dataclass(frozen=True)
class SplitSuggestion:
    playlist_id: int
    # Cluster labels this playlist straddles, with the track share of each.
    clusters: list[tuple[int, float]]


@dataclass(frozen=True)
class MergeSuggestion:
    cluster: int
    playlist_ids: list[int]


@dataclass(frozen=True)
class TrackMapResult:
    points: list[MapPoint]
    cluster_count: int
    noise_count: int
    # Adjusted Rand index between cluster labels and playlist assignment,
    # over clustered tracks that belong to at least one playlist.
    ari: float | None
    split_suggestions: list[SplitSuggestion]
    merge_suggestions: list[MergeSuggestion]
    # sha256 of the rounded layout — identical input must reproduce it.
    layout_hash: str


def compute_track_map(
    matrix: np.ndarray,
    track_ids: list[int],
    memberships: dict[int, set[int]],
    genre_matrix: np.ndarray | None = None,
) -> TrackMapResult | None:
    """Project the library and compare its density structure to the playlists.

    ``matrix`` rows are percentile vectors aligned with ``track_ids``;
    ``memberships`` maps playlist id -> track ids. ``genre_matrix``, when
    given, is a pre-weighted per-track genre block (rows aligned with
    ``track_ids``) concatenated onto the acoustic block before projection so
    genre-distinct groups separate. Returns None below MIN_TRACKS_FOR_MAP — a
    projection of a handful of points is noise wearing axes.

    Two embeddings: a display embedding (min_dist=0.1) for the on-screen
    x/y, and a clustering embedding (nn=30, min_dist=0) that HDBSCAN clusters.
    The cluster labels are painted onto the display layout.
    """
    n = matrix.shape[0] if matrix.size else 0
    if n < MIN_TRACKS_FOR_MAP:
        return None

    # Imported here: umap triggers numba JIT machinery on import, which app
    # startup should not pay for.
    from sklearn.cluster import HDBSCAN
    from sklearn.metrics import adjusted_rand_score
    from umap import UMAP

    # Blend the pre-weighted genre block onto the acoustic block. Both
    # embeddings project the same combined feature space.
    features = matrix
    if genre_matrix is not None and genre_matrix.size:
        genre_matrix = np.asarray(genre_matrix, dtype=float)
        features = np.hstack([matrix, genre_matrix])

    # Display embedding: what the field renders (min_dist spaces points out).
    embedding = UMAP(
        n_components=2,
        n_neighbors=min(DISPLAY_NEIGHBORS, n - 1),
        min_dist=DISPLAY_MIN_DIST,
        random_state=UMAP_SEED,
    ).fit_transform(features)
    embedding = np.asarray(embedding, dtype=float)

    # Clustering embedding: tuned for density — HDBSCAN clusters THIS, not
    # the raw matrix, so hulls match the geography and the blob breaks apart.
    cluster_embedding = UMAP(
        n_components=2,
        n_neighbors=min(CLUSTER_NEIGHBORS, n - 1),
        min_dist=CLUSTER_MIN_DIST,
        random_state=UMAP_SEED,
    ).fit_transform(features)
    cluster_embedding = np.asarray(cluster_embedding, dtype=float)

    labels = HDBSCAN(min_cluster_size=scaled_min_cluster_size(n), copy=True).fit_predict(
        cluster_embedding
    )

    points = [
        MapPoint(
            track_id=tid,
            x=float(embedding[i, 0]),
            y=float(embedding[i, 1]),
            cluster=int(labels[i]),
        )
        for i, tid in enumerate(track_ids)
    ]

    cluster_by_track = {tid: int(labels[i]) for i, tid in enumerate(track_ids)}
    cluster_count = len({label for label in labels.tolist() if label != -1})
    noise_count = int((labels == -1).sum())

    # ARI needs one playlist label per track; tracks in several playlists take
    # the smallest playlist id (stable, if arbitrary). Noise tracks and tracks
    # outside every playlist are excluded from the comparison.
    playlist_by_track: dict[int, int] = {}
    for pid in sorted(memberships):
        for tid in memberships[pid]:
            playlist_by_track.setdefault(tid, pid)
    paired = [
        (playlist_by_track[tid], cluster_by_track[tid])
        for tid in track_ids
        if tid in playlist_by_track and cluster_by_track[tid] != -1
    ]
    ari: float | None = None
    if paired:
        playlist_labels, cluster_labels = zip(*paired, strict=True)
        ari = float(adjusted_rand_score(playlist_labels, cluster_labels))

    split_suggestions: list[SplitSuggestion] = []
    cluster_shares: dict[int, dict[int, float]] = {}
    for pid in sorted(memberships):
        counts: dict[int, int] = {}
        for tid in memberships[pid]:
            label = cluster_by_track.get(tid, -1)
            if label != -1:
                counts[label] = counts.get(label, 0) + 1
        clustered = sum(counts.values())
        if clustered == 0:
            continue
        shares = {label: count / clustered for label, count in counts.items()}
        cluster_shares[pid] = shares
        straddled = sorted(
            (label, share)
            for label, share in shares.items()
            if share >= SPLIT_MIN_SHARE and counts[label] >= SPLIT_MIN_MEMBERS
        )
        if len(straddled) >= 2:
            split_suggestions.append(SplitSuggestion(playlist_id=pid, clusters=straddled))

    merge_suggestions: list[MergeSuggestion] = []
    dominant: dict[int, list[int]] = {}
    for pid, shares in cluster_shares.items():
        label, share = max(shares.items(), key=lambda item: item[1])
        if share >= MERGE_DOMINANT_SHARE:
            dominant.setdefault(label, []).append(pid)
    for label in sorted(dominant):
        pids = sorted(dominant[label])
        if len(pids) >= 2:
            merge_suggestions.append(MergeSuggestion(cluster=label, playlist_ids=pids))

    layout_hash = hashlib.sha256(np.round(embedding, 4).tobytes()).hexdigest()

    return TrackMapResult(
        points=points,
        cluster_count=cluster_count,
        noise_count=noise_count,
        ari=ari,
        split_suggestions=split_suggestions,
        merge_suggestions=merge_suggestions,
        layout_hash=layout_hash,
    )
