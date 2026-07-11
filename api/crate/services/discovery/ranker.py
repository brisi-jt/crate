"""Fit scoring and ranking for discovery candidates.

Pure functions: given the same candidate vectors, playlist centroid, affinity
weights, suggestion counts, and feedback tallies, the ordering is identical
every time (ties break on candidate id).

The fit score composes four signals:

- proximity  — how close the candidate sits to the playlist's centroid in
  percentile space (1 - Euclidean distance / unit-cube diagonal).
- affinity   — the strongest Last.fm listener-similarity edge between the
  candidate's artist and the playlist's own artists.
- novelty    — a penalty that grows with how often the artist has already
  been suggested, so one artist never floods the queue.
- feedback   — a logistic re-weighting of the artist's accept/reject history:
  each decision shifts future fits toward or away from that artist, bounded
  so history informs the ranking without overwhelming the acoustics.
"""

import math
from dataclasses import dataclass

# Fit weights: acoustic proximity dominates; artist affinity seasons.
PROXIMITY_WEIGHT = 0.7
AFFINITY_WEIGHT = 0.3

# Each prior suggestion of the same artist costs this much fit, up to the cap.
NOVELTY_STEP = 0.05
NOVELTY_CAP = 0.25

# The most feedback can move a fit in either direction.
FEEDBACK_SPAN = 0.3

# Percentile rank assumed for features the candidate is missing — the library
# median, so gaps neither attract nor repel.
NEUTRAL_RANK = 0.5


@dataclass(frozen=True)
class RankInput:
    """Everything the ranker needs to know about one candidate."""

    candidate_id: int
    # feature -> percentile rank in the library space (may be sparse/empty).
    vector: dict[str, float]
    # Strongest similarity weight from a playlist artist to this artist, 0..1.
    affinity: float
    # How many times this artist has been suggested before (any playlist).
    prior_suggestions: int
    accepts: int
    rejects: int


@dataclass(frozen=True)
class FitBreakdown:
    """The fit score with each contributing component, for the deck readout."""

    proximity: float
    affinity: float
    novelty: float
    feedback: float
    fit: float

    def as_dict(self) -> dict[str, float]:
        return {
            "proximity": round(self.proximity, 4),
            "affinity": round(self.affinity, 4),
            "novelty": round(self.novelty, 4),
            "feedback": round(self.feedback, 4),
            "fit": round(self.fit, 4),
        }


@dataclass(frozen=True)
class RankedCandidate:
    candidate_id: int
    breakdown: FitBreakdown


def feedback_adjustment(accepts: int, rejects: int) -> float:
    """Logistic re-weighting of accept/reject history, in ±FEEDBACK_SPAN.

    sigma(accepts - rejects) recentred on zero: no history is neutral, each
    accept pushes toward +SPAN, each reject toward -SPAN, saturating so a long
    history can never dominate the acoustic terms.
    """
    # Clamped so extreme histories can't overflow exp(); ±40 already
    # saturates the logistic to machine precision.
    balance = max(-40.0, min(40.0, float(accepts - rejects)))
    sigma = 1.0 / (1.0 + math.exp(-balance))
    return FEEDBACK_SPAN * 2.0 * (sigma - 0.5)


def _proximity(vector: dict[str, float], centroid: dict[str, float]) -> float:
    """1 - normalized Euclidean distance to the centroid in percentile space."""
    if not centroid:
        return NEUTRAL_RANK
    squared = 0.0
    for feature, target in centroid.items():
        value = vector.get(feature, NEUTRAL_RANK)
        squared += (value - target) ** 2
    distance = math.sqrt(squared) / math.sqrt(len(centroid))
    return max(0.0, 1.0 - distance)


def fit_breakdown(entry: RankInput, centroid: dict[str, float]) -> FitBreakdown:
    proximity = _proximity(entry.vector, centroid)
    novelty = min(NOVELTY_CAP, NOVELTY_STEP * max(0, entry.prior_suggestions))
    feedback = feedback_adjustment(entry.accepts, entry.rejects)
    raw = PROXIMITY_WEIGHT * proximity + AFFINITY_WEIGHT * entry.affinity - novelty + feedback
    return FitBreakdown(
        proximity=proximity,
        affinity=entry.affinity,
        novelty=novelty,
        feedback=feedback,
        fit=min(1.0, max(0.0, raw)),
    )


def rank(entries: list[RankInput], centroid: dict[str, float]) -> list[RankedCandidate]:
    """Highest fit first; equal fits order by candidate id."""
    scored = [
        RankedCandidate(candidate_id=entry.candidate_id, breakdown=fit_breakdown(entry, centroid))
        for entry in entries
    ]
    return sorted(scored, key=lambda item: (-item.breakdown.fit, item.candidate_id))
