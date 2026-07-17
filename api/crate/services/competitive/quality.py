"""F6 — a single quality figure per playlist, from four explainable sub-scores.

Chosic ships a 0-5 playlist rating; crate already computes the harder inputs
(cohesion, duplicate detection, flow) as part of its analytics survey, so F6
packages them as one headline plus a transparent breakdown. Every sub-score is
0..1 with 1 = good, and carries its own ``metric_ref`` so the web attaches a
per-limb explain (X1). The headline is the mean of the sub-scores that could be
computed — a missing input (e.g. a one-track playlist has no cohesion or flow)
is excluded, never counted as a zero that would unfairly tank the score.

Pure transforms of already-computed numbers; the ORM reads live in the engine.
"""

from datetime import datetime
from statistics import mean
from typing import Any

# The metric_ref for each sub-score (glossary keys + X1 attach points).
SUBSCORE_REFS: tuple[str, ...] = (
    "quality_cohesion",
    "quality_uniqueness",
    "quality_freshness",
    "quality_flow",
)

# Freshness half-life: a playlist untended for this many days scores 0.5 on the
# freshness limb, decaying smoothly toward 0. 90 days ≈ a season — long enough
# that a monthly-tended playlist still reads fresh, short enough that a
# genuinely abandoned one sinks.
FRESHNESS_HALFLIFE_DAYS = 90.0


def freshness_subscore(newest_added_at: datetime | None, *, now: datetime) -> float:
    """How recently the playlist was tended, 1 (today) decaying toward 0.

    ``newest_added_at`` is the most recent track-add timestamp. A playlist that
    has never had a dated add scores 0 — it reads as fully dormant. Decay is a
    half-life curve on days-since-newest-add.
    """
    if newest_added_at is None:
        return 0.0
    days = max(0.0, (now - newest_added_at).total_seconds() / 86400.0)
    return round(0.5 ** (days / FRESHNESS_HALFLIFE_DAYS), 4)


def playlist_quality(
    *,
    cohesion: float | None,
    duplicate_fraction: float | None,
    newest_added_at: datetime | None,
    flow_score: float | None,
    now: datetime,
) -> dict[str, Any]:
    """Headline quality + the four sub-scores, each 0..1 (1 = good).

    - ``cohesion`` is the analytics cohesion (0 = uniform, 1 = spread), so the
      sub-score inverts it: a tight playlist scores high.
    - ``duplicate_fraction`` is the share of a playlist's slots taken by a
      repeated track; uniqueness is its complement.
    - freshness comes from ``newest_added_at`` (see ``freshness_subscore``).
    - ``flow_score`` is the 0-100 transition score; the sub-score scales it to
      0..1.

    None inputs drop their limb from the blend (freshness always contributes,
    since None there is the real "never tended" signal).
    """
    subs: list[dict[str, Any]] = []
    if cohesion is not None:
        subs.append(
            {
                "ref": "quality_cohesion",
                "label": "cohesion",
                "value": round(1.0 - cohesion, 4),
            }
        )
    if duplicate_fraction is not None:
        subs.append(
            {
                "ref": "quality_uniqueness",
                "label": "uniqueness",
                "value": round(1.0 - duplicate_fraction, 4),
            }
        )
    subs.append(
        {
            "ref": "quality_freshness",
            "label": "freshness",
            "value": freshness_subscore(newest_added_at, now=now),
        }
    )
    if flow_score is not None:
        subs.append(
            {
                "ref": "quality_flow",
                "label": "flow",
                "value": round(flow_score / 100.0, 4),
            }
        )

    values = [s["value"] for s in subs]
    return {
        "score": round(mean(values), 4) if values else None,
        "subscores": subs,
    }
