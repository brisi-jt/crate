"""Pure ordering primitives for radio sessions.

The session backbone is library material ordered for listening flow (the
Phase-4 Camelot/BPM transition scoring); discovery candidates are spread
through it at evenly-spaced slots so audition moments arrive at a steady
cadence instead of front-loading.
"""

import math

from crate.services.analytics.flow import TrackAudio, camelot, suggest_order


def discovery_slots(*, total: int, count: int) -> list[int]:
    """``count`` positions spread evenly across ``total`` session slots.

    Slots sit at the interior division points of the session, so a run never
    opens or (usually) closes on a discovery item. Guaranteed distinct and
    in-range for any count <= total.
    """
    if total <= 0 or count <= 0:
        return []
    count = min(count, total)
    slots: list[int] = []
    used: set[int] = set()
    for index in range(count):
        ideal = math.floor((index + 1) * total / (count + 1))
        slot = min(ideal, total - 1)
        while slot in used:  # dense sessions: shift right, wrap if needed
            slot = (slot + 1) % total
        used.add(slot)
        slots.append(slot)
    return sorted(slots)


def flow_order(tracks: list[TrackAudio]) -> list[int]:
    """Track ids in flow-aware play order, starting from the given opener.

    Below three tracks (the reorder heuristic's floor) the input order stands.
    """
    if len(tracks) < 3:
        return [track.track_id for track in tracks]
    suggestion = suggest_order(tracks)
    if suggestion is None:
        return [track.track_id for track in tracks]
    return suggestion.order


def camelot_label(key: int | None, mode: int | None) -> str | None:
    """Camelot wheel readout ("8B") for a pitch class and mode, when known."""
    position = camelot(key, mode)
    if position is None:
        return None
    number, ring = position
    return f"{number}{ring}"


def euclidean(a: dict[str, float], b: dict[str, float], features: tuple[str, ...]) -> float:
    """Distance between two percentile vectors over a fixed feature order."""
    return math.sqrt(sum((a.get(f, 0.5) - b.get(f, 0.5)) ** 2 for f in features))
