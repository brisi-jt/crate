"""Artist-galaxy assembly: co-playlist weighting, degree ranking, edge caps.

Pure functions over plain structures — the engine loads the library and
wires these into the /v1/graph/artists payload.

Caps: the galaxy renders on one canvas, so the payload is bounded. Nodes are
kept by descending co-playlist degree (distinct partners), then library
track count, then name — the artists that connect the most playlists stay on
the map. Edges keep every similarity edge (rare, externally sourced) and the
heaviest co-playlist edges up to the budget.
"""

from collections import Counter
from itertools import combinations
from typing import Any

# One canvas frame paints every node and edge — these budgets keep a
# real-size library (thousands of credited artists) inside a smooth frame.
MAX_GALAXY_NODES = 300
MAX_GALAXY_EDGES = 1500


def co_playlist_weights(
    playlist_artists: dict[int, set[str]],
) -> dict[tuple[str, str], int]:
    """(artist, artist) sorted pair -> number of playlists holding both."""
    weights: Counter[tuple[str, str]] = Counter()
    for artists in playlist_artists.values():
        for pair in combinations(sorted(artists), 2):
            weights[pair] += 1
    return dict(weights)


def order_by_degree(
    artist_keys: list[str],
    weights: dict[tuple[str, str], int],
    track_counts: dict[str, int],
) -> list[str]:
    """Artists by descending co-playlist degree, track count, then name."""
    degree: Counter[str] = Counter()
    for a, b in weights:
        degree[a] += 1
        degree[b] += 1
    return sorted(
        artist_keys,
        key=lambda key: (-degree[key], -track_counts.get(key, 0), key),
    )


def cap_edges(
    co_playlist: list[dict[str, Any]],
    similarity: list[dict[str, Any]],
    max_edges: int = MAX_GALAXY_EDGES,
) -> list[dict[str, Any]]:
    """Every similarity edge, then the heaviest co-playlist edges to budget."""
    kept = list(similarity)
    budget = max(0, max_edges - len(kept))
    heaviest = sorted(
        co_playlist,
        key=lambda edge: (-edge["weight"], edge["source"], edge["target"]),
    )
    kept.extend(heaviest[:budget])
    return kept
