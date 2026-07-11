"""Structure metrics: playlist overlap, duplicates, cohesion, outliers."""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np

# Containment at or above this makes the smaller playlist a subset of the
# larger for graph purposes (dashed edge + satellite ring in the UI).
SUBSET_CONTAINMENT = 0.9

# How many outlier tracks a playlist reports.
DEFAULT_OUTLIER_COUNT = 5


def jaccard(a: set[int], b: set[int]) -> float:
    """Shared share of the union; 0 when either side is empty."""
    if not a or not b:
        return 0.0
    shared = len(a & b)
    return shared / len(a | b)


def containment(a: set[int], b: set[int]) -> float:
    """Shared share of the smaller set — 1.0 means one fully contains the other."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass(frozen=True)
class OverlapEdge:
    source: int
    target: int
    shared: int
    jaccard: float
    containment: float
    subset: bool


def overlap_edges(memberships: dict[int, set[int]]) -> list[OverlapEdge]:
    """All playlist pairs that share at least one track, source id < target id."""
    edges: list[OverlapEdge] = []
    for (pid_a, set_a), (pid_b, set_b) in combinations(sorted(memberships.items()), 2):
        shared = len(set_a & set_b)
        if shared == 0:
            continue
        cont = containment(set_a, set_b)
        edges.append(
            OverlapEdge(
                source=pid_a,
                target=pid_b,
                shared=shared,
                jaccard=jaccard(set_a, set_b),
                containment=cont,
                subset=cont >= SUBSET_CONTAINMENT,
            )
        )
    return edges


@dataclass(frozen=True)
class DuplicateGroup:
    isrc: str | None
    name: str
    artist: str
    playlists: list[str] = field(default_factory=list)


def find_duplicate_groups(
    tracks: list[dict[str, Any]],
    memberships: dict[int, set[int]],
    playlist_names: dict[int, str],
    occurrences: dict[int, list[int]] | None = None,
) -> list[DuplicateGroup]:
    """Two duplicate shapes, both invisible to Spotify's own dedupe:

    - the same recording (one ISRC) under two or more Spotify track ids
    - the same track id at two or more positions inside one playlist

    A track merely appearing in several playlists is normal curation, not a
    duplicate. `tracks` rows carry track_id/spotify_id/isrc/name/artist;
    `occurrences` maps playlist id -> track ids in position order (needed to
    see within-playlist repeats).
    """
    by_id = {track["track_id"]: track for track in tracks}
    groups: list[DuplicateGroup] = []

    by_isrc: dict[str, list[dict[str, Any]]] = {}
    for track in tracks:
        if track.get("isrc"):
            by_isrc.setdefault(track["isrc"], []).append(track)
    for isrc, rows in sorted(by_isrc.items()):
        spotify_ids = {row["spotify_id"] for row in rows}
        if len(spotify_ids) < 2:
            continue
        track_ids = {row["track_id"] for row in rows}
        playlist_ids = sorted(pid for pid, members in memberships.items() if members & track_ids)
        first = min(rows, key=lambda row: row["track_id"])
        groups.append(
            DuplicateGroup(
                isrc=isrc,
                name=first["name"],
                artist=first["artist"],
                playlists=[playlist_names.get(pid, str(pid)) for pid in playlist_ids],
            )
        )

    for pid, ordered_track_ids in sorted((occurrences or {}).items()):
        seen: set[int] = set()
        reported: set[int] = set()
        for track_id in ordered_track_ids:
            if track_id in seen and track_id not in reported and track_id in by_id:
                track = by_id[track_id]
                groups.append(
                    DuplicateGroup(
                        isrc=track.get("isrc"),
                        name=track["name"],
                        artist=track["artist"],
                        playlists=[playlist_names.get(pid, str(pid))],
                    )
                )
                reported.add(track_id)
            seen.add(track_id)

    return groups


def cohesion(vectors: np.ndarray) -> float | None:
    """Mean pairwise Euclidean distance in percentile space, scaled to [0, 1].

    The raw mean distance is divided by sqrt(n_features) — the diagonal of the
    unit hypercube — so 0 means identical tracks and 1 means maximally spread.
    None until the playlist has two enriched tracks to compare.
    """
    n = vectors.shape[0] if vectors.size else 0
    if n < 2:
        return None
    diffs = vectors[:, None, :] - vectors[None, :, :]
    distances = np.sqrt((diffs**2).sum(axis=2))
    upper = distances[np.triu_indices(n, k=1)]
    return float(upper.mean() / np.sqrt(vectors.shape[1]))


@dataclass(frozen=True)
class OutlierEntry:
    track_id: int
    distance: float


@dataclass(frozen=True)
class OutlierResult:
    method: str  # "mahalanobis" or "euclidean" (singular-covariance fallback)
    entries: list[OutlierEntry]


def outliers(vectors: np.ndarray, track_ids: list[int], top_n: int = 5) -> OutlierResult:
    """Top-N tracks farthest from the playlist's percentile centroid.

    Mahalanobis distance accounts for the playlist's own spread per feature;
    when the sample covariance is singular (small or degenerate playlists)
    the distance falls back to plain Euclidean from the centroid.
    """
    n = vectors.shape[0] if vectors.size else 0
    if n < 3:
        return OutlierResult(method="euclidean", entries=[])

    mean = vectors.mean(axis=0)
    centered = vectors - mean

    method = "mahalanobis"
    try:
        cov = np.cov(vectors, rowvar=False, ddof=1)
        cov = np.atleast_2d(cov)
        solved = np.linalg.solve(cov, centered.T)
        squared = (centered.T * solved).sum(axis=0)
        if np.any(squared < -1e-9) or not np.all(np.isfinite(squared)):
            raise np.linalg.LinAlgError("unstable covariance")
        distances = np.sqrt(np.clip(squared, 0.0, None))
    except np.linalg.LinAlgError:
        method = "euclidean"
        distances = np.sqrt((centered**2).sum(axis=1))

    ranked = sorted(zip(track_ids, distances.tolist(), strict=True), key=lambda t: (-t[1], t[0]))
    entries = [OutlierEntry(track_id=tid, distance=float(d)) for tid, d in ranked[:top_n]]
    return OutlierResult(method=method, entries=entries)
