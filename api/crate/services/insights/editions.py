"""Insight editions - the field journal.

An edition is a frozen weekly reading: the headline metrics at compile time
plus generated narrative lines describing what moved since the previous
edition. Edition 1 is the baseline reading (no deltas - it states the baseline
honestly). Week-keyed like digests; recompiling a week rebuilds its row.

Narrative generation is a pure diff over two headline dicts, so it is fully
offline-testable; the compile function wraps it with persistence.
"""

from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from crate.model.orm import InsightEdition, User
from crate.model.orm.base import utcnow
from crate.services.analytics.engine import AnalyticsContext
from crate.services.digest.service import week_start_for
from crate.services.insights.engine import compute_insights_payload


def extract_headline(payload: dict[str, Any]) -> dict[str, Any]:
    """The scalar readings an edition freezes and diffs against.

    Kept deliberately small - the numbers that carry the field-manual
    narrative, not the whole survey.
    """
    identity = payload["taste_identity"]
    archaeology = payload["archaeology"]
    return {
        "entropy_bits": identity["genre_entropy"]["entropy_bits"],
        "effective_genres": identity["genre_entropy"]["effective_genres"],
        "gs_score": identity["gs_score"],
        "archetype": identity["typology"]["archetype"],
        "mean_rarity": identity["genre_rarity"]["mean_rarity"],
        "enriched_tracks": payload["coverage"]["enriched_tracks"],
        "dormant_playlists": len(archaeology["abandoned_playlists"]),
        "fingerprint": {entry["feature"]: entry["percentile"] for entry in identity["fingerprint"]},
    }


# Movement below this magnitude isn't worth a narrative line.
_ENTROPY_EPS = 0.05
_GS_EPS = 0.02
_RARITY_EPS = 0.02
_FINGERPRINT_EPS = 0.05


def generate_narrative(
    current: dict[str, Any], previous: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Field-manual lines describing what moved current-vs-previous.

    previous is None for edition 1 - that baseline reading states the numbers
    plainly instead of diffing. Each line is {"kind", "text"}; kinds let the
    web tint by theme without parsing the prose.
    """
    if previous is None:
        lines = [
            {
                "kind": "baseline",
                "text": (
                    f"Baseline reading. {current['effective_genres']:.1f} effective genres "
                    f"across the library; classified {current['archetype']}."
                ),
            },
            {
                "kind": "baseline",
                "text": (
                    f"Acoustic sprawl reads {current['gs_score']:.2f}; "
                    f"{current['enriched_tracks']} tracks measured."
                )
                if current["gs_score"] is not None
                else f"{current['enriched_tracks']} tracks measured; sprawl pending enrichment.",
            },
        ]
        if current["dormant_playlists"]:
            lines.append(
                {
                    "kind": "dormancy",
                    "text": f"{current['dormant_playlists']} playlists already sit dormant.",
                }
            )
        return lines

    lines: list[dict[str, Any]] = []

    entropy_delta = current["entropy_bits"] - previous["entropy_bits"]
    if abs(entropy_delta) >= _ENTROPY_EPS:
        direction = "widened" if entropy_delta > 0 else "narrowed"
        lines.append(
            {
                "kind": "entropy",
                "text": (
                    f"Genre spread {direction} to {current['effective_genres']:.1f} effective "
                    f"genres ({entropy_delta:+.2f} bits)."
                ),
            }
        )

    gs_prev, gs_now = previous["gs_score"], current["gs_score"]
    if gs_prev is not None and gs_now is not None and abs(gs_now - gs_prev) >= _GS_EPS:
        direction = "outward" if gs_now > gs_prev else "inward"
        lines.append(
            {
                "kind": "sprawl",
                "text": (
                    f"Acoustic sprawl drifted {direction} to {gs_now:.2f} "
                    f"({gs_now - gs_prev:+.2f})."
                ),
            }
        )

    rarity_delta = current["mean_rarity"] - previous["mean_rarity"]
    if abs(rarity_delta) >= _RARITY_EPS:
        direction = "deeper into niche" if rarity_delta > 0 else "toward the mainstream"
        lines.append(
            {
                "kind": "rarity",
                "text": f"Taste moved {direction} ({rarity_delta:+.2f} rarity).",
            }
        )

    if current["archetype"] != previous["archetype"]:
        lines.append(
            {
                "kind": "archetype",
                "text": f"Reclassified {previous['archetype']} -> {current['archetype']}.",
            }
        )

    dormant_delta = current["dormant_playlists"] - previous["dormant_playlists"]
    if dormant_delta > 0:
        lines.append(
            {
                "kind": "dormancy",
                "text": f"{dormant_delta} more playlists went dormant.",
            }
        )

    # Largest fingerprint-axis movement, when it clears the threshold.
    drift = _dominant_drift(current["fingerprint"], previous["fingerprint"])
    if drift is not None:
        feature, delta = drift
        direction = "up" if delta > 0 else "down"
        lines.append(
            {
                "kind": "fingerprint",
                "text": f"Fingerprint drifted along {feature} ({direction} {abs(delta):.2f}).",
            }
        )

    if not lines:
        lines.append(
            {"kind": "steady", "text": "A steady week - no reading moved past its threshold."}
        )
    return lines


def _dominant_drift(
    current: dict[str, float], previous: dict[str, float]
) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for feature, value in current.items():
        if feature not in previous:
            continue
        delta = value - previous[feature]
        if abs(delta) < _FINGERPRINT_EPS:
            continue
        if best is None or abs(delta) > abs(best[1]):
            best = (feature, delta)
    return best


def _previous_edition(
    session: Session, user_id: int, week_start: datetime, owned_only: bool
) -> InsightEdition | None:
    return session.exec(
        select(InsightEdition)
        .where(InsightEdition.user_id == user_id)
        .where(InsightEdition.owned_only == owned_only)
        .where(col(InsightEdition.week_start) < week_start)
        .order_by(col(InsightEdition.week_start).desc())
    ).first()


def compile_edition(
    session: Session,
    user: User,
    *,
    week_start: datetime | None = None,
    owned_only: bool = True,
    ctx: AnalyticsContext | None = None,
) -> InsightEdition:
    """Compile (or rebuild) the edition for a week from the live insights.

    Diffs the fresh headline against the most recent earlier edition; edition 1
    (no earlier edition) is the baseline reading. Recompiling a week updates its
    row in place (like the digest), so counts stay stable.
    """
    assert user.id is not None
    start = week_start or week_start_for(utcnow())

    payload = compute_insights_payload(session, user, ctx, owned_only=owned_only)
    headline = extract_headline(payload)

    previous = _previous_edition(session, user.id, start, owned_only)
    narrative = generate_narrative(headline, previous.headline if previous else None)

    existing = session.exec(
        select(InsightEdition)
        .where(InsightEdition.user_id == user.id)
        .where(InsightEdition.week_start == start)
        .where(InsightEdition.owned_only == owned_only)
    ).first()
    if existing is not None:
        existing.headline = headline
        existing.narrative = narrative
        existing.generated_at = utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    # edition_number = one past the highest existing edition for this scope.
    highest = session.exec(
        select(InsightEdition.edition_number)
        .where(InsightEdition.user_id == user.id)
        .where(InsightEdition.owned_only == owned_only)
        .order_by(col(InsightEdition.edition_number).desc())
    ).first()
    edition = InsightEdition(
        user_id=user.id,
        week_start=start,
        edition_number=(highest or 0) + 1,
        owned_only=owned_only,
        generated_at=utcnow(),
        headline=headline,
        narrative=narrative,
    )
    session.add(edition)
    session.commit()
    session.refresh(edition)
    return edition


async def compile_edition_for_user(session: Session, user: User) -> InsightEdition:
    """Scheduler entry point - compiles the current week's owned-scope edition."""
    return compile_edition(session, user, owned_only=True)
