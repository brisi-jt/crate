"""Track map: seeded UMAP 2D projection + HDBSCAN clusters vs playlists.

UMAP runs with a fixed random_state (which forces single-threaded, exactly
reproducible layouts), so the same library always produces the same map.
HDBSCAN comes from scikit-learn — no separate hdbscan package.
"""

import hashlib
from dataclasses import dataclass

import numpy as np

UMAP_SEED = 42
UMAP_MIN_DIST = 0.1
UMAP_NEIGHBORS = 15

MIN_TRACKS_FOR_MAP = 10
MIN_CLUSTER_SIZE = 5

# A playlist is a split candidate when >= 2 clusters each hold this share of
# its clustered tracks (and at least MIN_CLUSTER_SIZE tracks).
SPLIT_MIN_SHARE = 0.3
# Playlists whose dominant cluster holds this share of their clustered tracks
# are merge candidates when they share that dominant cluster.
MERGE_DOMINANT_SHARE = 0.6


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
) -> TrackMapResult | None:
    """Project the library and compare its density structure to the playlists.

    matrix rows are percentile vectors aligned with track_ids; memberships
    maps playlist id -> track ids. Returns None below MIN_TRACKS_FOR_MAP —
    a projection of a handful of points is noise wearing axes.
    """
    n = matrix.shape[0] if matrix.size else 0
    if n < MIN_TRACKS_FOR_MAP:
        return None

    # Imported here: umap triggers numba JIT machinery on import, which app
    # startup should not pay for.
    from sklearn.cluster import HDBSCAN
    from sklearn.metrics import adjusted_rand_score
    from umap import UMAP

    embedding = UMAP(
        n_components=2,
        n_neighbors=min(UMAP_NEIGHBORS, n - 1),
        min_dist=UMAP_MIN_DIST,
        random_state=UMAP_SEED,
    ).fit_transform(matrix)
    embedding = np.asarray(embedding, dtype=float)

    labels = HDBSCAN(min_cluster_size=min(MIN_CLUSTER_SIZE, max(2, n // 2)), copy=True).fit_predict(
        matrix
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
            if share >= SPLIT_MIN_SHARE and counts[label] >= MIN_CLUSTER_SIZE
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
