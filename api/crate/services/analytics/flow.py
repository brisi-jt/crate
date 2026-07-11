"""Harmonic and tempo flow: Camelot key compatibility, BPM transitions,
and a greedy reorder suggestion.

Key and mode are the only feature values used at face value here — pitch
class and mode are categorical, so percentile calibration does not apply.
Tempo comparisons are relative (percent difference), never thresholded
against absolute BPM bands.
"""

from dataclasses import dataclass
from itertools import pairwise

import networkx as nx

# A transition scores the mean of its key and tempo components on 0..100.
KEY_WEIGHT = 0.5
BPM_WEIGHT = 0.5

# Relative tempo difference at which the BPM component reaches zero. 16%
# spans two nudges of a DJ pitch fader; half/double time counts as equal.
BPM_TOLERANCE = 0.16

# Component score when a track is missing key or tempo — unknown transitions
# neither reward nor punish an ordering.
NEUTRAL_COMPONENT = 0.5

Camelot = tuple[int, str]


def camelot(key: int | None, mode: int | None) -> Camelot | None:
    """(wheel number 1-12, ring) for a pitch class and mode.

    Ring B is major, ring A is minor. Anchors: C major = 8B, A minor = 8A.
    Minor keys map through their relative major (three semitones up).
    """
    if key is None or mode is None or not 0 <= key <= 11 or mode not in (0, 1):
        return None
    pitch = key if mode == 1 else (key + 3) % 12
    number = ((7 * pitch) % 12 + 7) % 12 + 1
    return number, "B" if mode == 1 else "A"


def key_score(a: Camelot | None, b: Camelot | None) -> float:
    """Compatibility of two wheel positions, 1.0 (mixable) to 0.0 (clash).

    Wheel distance counts steps around the ring (0-6). Switching ring at the
    same number is the relative major/minor — a perfect mix — while a ring
    switch combined with a number step costs one extra step.
    """
    if a is None or b is None:
        return NEUTRAL_COMPONENT
    num_a, ring_a = a
    num_b, ring_b = b
    raw = abs(num_a - num_b)
    distance = min(raw, 12 - raw)
    if ring_a != ring_b and distance > 0:
        distance += 1
    return max(0.0, 1.0 - distance / 6.0)


def bpm_score(a: float | None, b: float | None) -> float:
    """Tempo compatibility, 1.0 (same effective tempo) to 0.0 (unmixable).

    The comparison tries straight, half, and double time and keeps the best
    match, so 60 -> 120 BPM scores as identical.
    """
    if not a or not b or a <= 0 or b <= 0:
        return NEUTRAL_COMPONENT
    best = min(abs(a * m - b) / max(a * m, b) for m in (0.5, 1.0, 2.0))
    return max(0.0, 1.0 - best / BPM_TOLERANCE)


@dataclass(frozen=True)
class TrackAudio:
    """The slice of a track's features that flow scoring needs."""

    track_id: int
    tempo: float | None
    key: int | None
    mode: int | None


def transition_score(a: TrackAudio, b: TrackAudio) -> float:
    """Quality of playing b after a, on 0..100."""
    key_component = key_score(camelot(a.key, a.mode), camelot(b.key, b.mode))
    bpm_component = bpm_score(a.tempo, b.tempo)
    return (KEY_WEIGHT * key_component + BPM_WEIGHT * bpm_component) * 100.0


def flow_score(ordered: list[TrackAudio]) -> float | None:
    """Mean transition score across the playlist's current order (0..100)."""
    if len(ordered) < 2:
        return None
    scores = [transition_score(a, b) for a, b in pairwise(ordered)]
    return sum(scores) / len(scores)


@dataclass(frozen=True)
class OrderSuggestion:
    order: list[int]  # track ids, best-first
    score: float  # flow score of the suggested order, 0..100


def suggest_order(tracks: list[TrackAudio]) -> OrderSuggestion | None:
    """Greedy nearest-neighbour reorder starting from the current opener.

    Transition costs (100 - score) form a complete graph; the greedy TSP tour
    from the first track, with its closing edge dropped, is the suggested
    play order. Deterministic for a given input order.
    """
    if len(tracks) < 3:
        return None
    graph = nx.Graph()
    for track in tracks:
        graph.add_node(track.track_id)
    for i, a in enumerate(tracks):
        for b in tracks[i + 1 :]:
            graph.add_edge(a.track_id, b.track_id, weight=100.0 - transition_score(a, b))

    cycle = nx.approximation.greedy_tsp(graph, source=tracks[0].track_id)
    order = cycle[:-1]  # drop the wrap-around back to the opener

    by_id = {track.track_id: track for track in tracks}
    score = flow_score([by_id[tid] for tid in order])
    if score is None:
        return None
    return OrderSuggestion(order=order, score=score)
