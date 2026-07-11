"""Pure artist-galaxy assembly tests — hand-computed micro-fixtures.

Fixture used throughout: three playlists over four artists.

  P1 holds artists {a, b}
  P2 holds artists {b, c}
  P3 holds artists {a, c}
  P4 holds artists {a, b, c, d}

Co-playlist weights (playlists holding both):
  (a,b): P1, P4          -> 2
  (a,c): P3, P4          -> 2
  (b,c): P2, P4          -> 2
  (a,d)/(b,d)/(c,d): P4  -> 1 each

Degree (distinct partners): a=3, b=3, c=3, d=3 — ties broken by track
count, then name.
"""

import pytest

from crate.services.analytics.galaxy import (
    cap_edges,
    co_playlist_weights,
    order_by_degree,
)

pytestmark = pytest.mark.unit

PLAYLIST_ARTISTS = {
    1: {"a", "b"},
    2: {"b", "c"},
    3: {"a", "c"},
    4: {"a", "b", "c", "d"},
}


def test_co_playlist_weights_count_shared_playlists():
    weights = co_playlist_weights(PLAYLIST_ARTISTS)
    assert weights[("a", "b")] == 2
    assert weights[("a", "c")] == 2
    assert weights[("b", "c")] == 2
    assert weights[("a", "d")] == 1
    assert weights[("b", "d")] == 1
    assert weights[("c", "d")] == 1
    assert len(weights) == 6


def test_co_playlist_weights_pairs_are_sorted_and_never_self():
    weights = co_playlist_weights({1: {"z", "a"}})
    assert list(weights) == [("a", "z")]
    assert co_playlist_weights({1: {"solo"}}) == {}


def test_order_by_degree_ranks_partner_count_then_track_count_then_name():
    weights = co_playlist_weights(PLAYLIST_ARTISTS)
    track_counts = {"a": 5, "b": 9, "c": 5, "d": 1}
    ordered = order_by_degree(["a", "b", "c", "d"], weights, track_counts)
    # All four artists have degree 3 -> track count decides, then name.
    assert ordered == ["b", "a", "c", "d"]


def test_order_by_degree_prefers_connected_artists():
    weights = co_playlist_weights({1: {"a", "b"}})
    ordered = order_by_degree(["a", "b", "loner"], weights, {"loner": 100})
    # Degree beats track count: the isolated artist sinks despite its size.
    assert ordered == ["a", "b", "loner"]


def test_cap_edges_keeps_all_similarity_then_heaviest_co_playlist():
    co = [
        {"source": "a", "target": "b", "kind": "co_playlist", "weight": 3.0},
        {"source": "a", "target": "c", "kind": "co_playlist", "weight": 1.0},
        {"source": "b", "target": "c", "kind": "co_playlist", "weight": 2.0},
    ]
    similarity = [
        {"source": "a", "target": "b", "kind": "similarity", "weight": 0.4},
    ]
    kept = cap_edges(co, similarity, max_edges=3)
    kinds = [(e["kind"], e["weight"]) for e in kept]
    # Similarity survives the cap; co-playlist edges kept heaviest-first.
    assert ("similarity", 0.4) in kinds
    assert ("co_playlist", 3.0) in kinds
    assert ("co_playlist", 2.0) in kinds
    assert len(kept) == 3


def test_cap_edges_no_cap_needed_keeps_everything_in_stable_order():
    co = [{"source": "a", "target": "b", "kind": "co_playlist", "weight": 1.0}]
    similarity = [
        {"source": "a", "target": "b", "kind": "similarity", "weight": 0.9},
    ]
    kept = cap_edges(co, similarity, max_edges=10)
    assert len(kept) == 2
