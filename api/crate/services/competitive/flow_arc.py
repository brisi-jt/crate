"""F4 — mood-arc + artist-separation reorder over the Camelot/BPM flow.

The base reorder (``analytics.flow.suggest_order``) is a greedy key+tempo TSP.
F4 keeps that transition machinery and adds two DJ constraints as extra edge
costs in a greedy build:

- mood arc          — each position has a target energy along a chosen arc
                      (rising / falling / peak); a track's cost includes how far
                      its energy sits from that position's target.
- artist separation — a track by the same artist as one of the last few placed
                      pays a penalty, so an artist never clumps.

The build is greedy and deterministic: at each slot, pick the unplaced track
with the lowest combined cost (ties break on track id). The output is a plain
permutation the engine feeds to ``MutationService.reorder`` — F4 emits its
result through the existing journaled write path, never a parallel one.
"""

from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from crate.services.analytics.flow import TrackAudio, flow_score, transition_score


class ArcMood(StrEnum):
    """The energy trajectory the reorder aims the set at."""

    rising = "rising"
    falling = "falling"
    peak = "peak"


@dataclass(frozen=True)
class ArcTrack(TrackAudio):
    """A flow track plus the two fields the arc + separation constraints read."""

    energy: float = 0.5  # energy percentile, 0..1
    artist_key: str = ""  # casefolded primary-artist key, for separation


# Weight of the mood-arc deviation in the combined cost. The transition cost is
# 0..100 (100 - flow score); arc deviation is 0..1 (|energy - target|), so this
# scale puts a full-swing arc miss on the order of a mediocre transition —
# enough to steer the shape without overriding harmonic mixing outright.
ARC_WEIGHT = 60.0

# Penalty added when a candidate shares an artist with one of the last
# ``SEPARATION_WINDOW`` placed tracks. Large relative to a transition so the
# build avoids a same-artist adjacency whenever any alternative exists.
SEPARATION_PENALTY = 200.0
SEPARATION_WINDOW = 2


def arc_target(mood: ArcMood, position: int, total: int) -> float:
    """Target energy (0..1) for ``position`` of ``total`` under ``mood``.

    Rising ramps 0→1, falling ramps 1→0, peak rises to an apex at the midpoint
    then falls. A single-slot set targets the midpoint.
    """
    if total <= 1:
        return 0.5
    frac = position / (total - 1)
    if mood is ArcMood.rising:
        return frac
    if mood is ArcMood.falling:
        return 1.0 - frac
    # peak: triangle 0 → 1 (mid) → 0.
    return 1.0 - abs(frac - 0.5) * 2.0


@dataclass(frozen=True)
class ArcSuggestion:
    order: list[int]  # track ids, play order
    flow_score: float  # base key/tempo flow of the arc order, 0..100
    adjacent_artist_repeats: int  # same-artist adjacencies left in the order


def _slot_cost(track: ArcTrack, placed: list[ArcTrack], target: float) -> tuple[float, int]:
    """Cost of placing ``track`` next: transition + arc deviation + separation.

    Ties break on track id so the greedy build is deterministic.
    """
    transition = 0.0 if not placed else 100.0 - transition_score(placed[-1], track)
    arc = ARC_WEIGHT * abs(track.energy - target)
    separation = 0.0
    if track.artist_key:
        recent = placed[-SEPARATION_WINDOW:]
        if any(p.artist_key == track.artist_key for p in recent):
            separation = SEPARATION_PENALTY
    return (transition + arc + separation, track.track_id)


def suggest_arc_order(tracks: list[ArcTrack], *, mood: ArcMood) -> ArcSuggestion | None:
    """Greedy mood-arc + artist-separation reorder. None under three tracks."""
    if len(tracks) < 3:
        return None

    by_id = {t.track_id: t for t in tracks}
    remaining = {t.track_id for t in tracks}
    total = len(tracks)
    order: list[int] = []
    placed: list[ArcTrack] = []

    for position in range(total):
        target = arc_target(mood, position, total)
        chosen = min(remaining, key=lambda tid: _slot_cost(by_id[tid], placed, target))
        order.append(chosen)
        placed.append(by_id[chosen])
        remaining.discard(chosen)

    ordered_audio = [by_id[tid] for tid in order]
    score = flow_score(ordered_audio) or 0.0
    repeats = sum(1 for a, b in pairwise(placed) if a.artist_key and a.artist_key == b.artist_key)
    return ArcSuggestion(
        order=order,
        flow_score=round(score, 2),
        adjacent_artist_repeats=repeats,
    )
