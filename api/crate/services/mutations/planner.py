"""Reconcile planner: minimal Spotify write calls from listing A to listing B.

Spotify's API constrains the moves: removal drops ALL occurrences of a URI,
and additions/reorders work on positions. The planner turns an arbitrary
(current, target) pair into remove → add → move steps that reproduce the
target exactly — membership and order — under those semantics.

Chosen shape: one remove call for every over-represented URI, one append call
for everything missing afterwards, then single-item moves (selection sort)
until the order matches. Never more than a handful of calls at playlist scale,
and additions keep their Spotify added_at everywhere except re-added
duplicates (the API offers no better primitive).
"""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoveStep:
    """Remove every occurrence of each URI."""

    uris: tuple[str, ...]


@dataclass(frozen=True)
class AddStep:
    """Insert URIs at a position (None = append)."""

    uris: tuple[str, ...]
    position: int | None


@dataclass(frozen=True)
class MoveStep:
    """Move the item at range_start to sit before insert_before (pre-move indices)."""

    range_start: int
    insert_before: int


Step = RemoveStep | AddStep | MoveStep


def plan_reconcile(current: list[str], target: list[str]) -> list[Step]:
    steps: list[Step] = []
    current_counts = Counter(current)
    target_counts = Counter(target)

    # 1. Remove URIs with too many occurrences. The API removes ALL of them;
    #    kept occurrences are re-added below.
    over = {uri for uri, count in current_counts.items() if count > target_counts.get(uri, 0)}
    if over:
        ordered = tuple(dict.fromkeys(u for u in current if u in over))
        steps.append(RemoveStep(uris=ordered))
    work = [u for u in current if u not in over]

    # 2. Append everything the target still lacks, in target order.
    available = Counter(work)
    missing: list[str] = []
    for uri in target:
        if available[uri] > 0:
            available[uri] -= 1
        else:
            missing.append(uri)
    if missing:
        steps.append(AddStep(uris=tuple(missing), position=None))
        work = work + missing

    # 3. Fix the order with single-item moves.
    for i, wanted in enumerate(target):
        if work[i] == wanted:
            continue
        j = work.index(wanted, i + 1)
        steps.append(MoveStep(range_start=j, insert_before=i))
        work.insert(i, work.pop(j))

    return steps
