"""Insights read endpoints — the survey, the field journal, and canvas pins.

Everything is served from the AnalyticsSnapshot cache (SnapshotKind.insights):
the first read after a sync or enrichment pass computes and stores, later reads
serve the stored payload. All feature-derived numbers are library percentiles
(0..1); tempo is raw BPM and release years are calendar years.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlmodel import col, select

from crate.deps import CurrentUserDep, SessionDep
from crate.errors import AppError, ProblemDetail
from crate.model.enums import SnapshotKind
from crate.model.orm import InsightEdition
from crate.services.analytics.engine import compute_artist_galaxy_payload
from crate.services.analytics.snapshots import get_or_compute
from crate.services.insights import editions as editions_service
from crate.services.insights.engine import compute_insights_payload
from crate.services.insights.pins import compute_pins_payload

router = APIRouter(tags=["insights"])

OwnedOnlyParam = Annotated[
    bool,
    Query(
        description=(
            "Limit insights to playlists the account owns. Set false to also "
            "include followed playlists — a much larger set on most accounts."
        )
    ),
]

SurfaceParam = Annotated[
    str,
    Query(
        description=(
            "Which canvas the pins annotate: graph (playlist graph), field "
            "(track sound map), or galaxy (artist galaxy)."
        )
    ),
]


class HalLink(BaseModel):
    href: str


# The survey payload is a nested, section-shaped body; the web consumes it as a
# whole, so it's typed loosely here and documented by the handoff rather than
# split into a hundred sub-models. The individual sections carry their own
# coverage so pending states render without guessing.
class InsightsResponse(BaseModel):
    """The full insights survey in one call, grouped into page sections.

    Sections: coverage (how much of the library is enriched / dated), taste
    identity (fingerprint, genre entropy, generalist-specialist score,
    archetype, genre shares and rarity), sonic signatures (Camelot wheel, mood
    quadrants, tempo histogram, feature ridgelines), archaeology (adds over
    time, abandoned playlists), eras (decade profile and the taste-freeze
    reading), and extremes (the superlatives board).
    """

    coverage: dict[str, Any]
    taste_identity: dict[str, Any]
    sonic_signatures: dict[str, Any]
    archaeology: dict[str, Any]
    eras: dict[str, Any]
    extremes: list[dict[str, Any]]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class EditionResource(BaseModel):
    """One frozen weekly reading from the field journal."""

    id: int
    edition_number: int = Field(description="Human-facing sequence; edition 1 is the baseline.")
    week_start: str = Field(description="Monday (UTC) of the week the edition covers.")
    generated_at: str
    owned_only: bool
    headline: dict[str, Any] = Field(description="The scalar readings frozen at compile time.")
    narrative: list[dict[str, Any]] = Field(
        description="Field-manual lines describing what moved since the previous edition."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class EditionSummary(BaseModel):
    id: int
    edition_number: int
    week_start: str
    generated_at: str
    owned_only: bool
    line_count: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class EditionCollection(BaseModel):
    items: list[EditionSummary]
    total: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class PinResource(BaseModel):
    anchor: str = Field(description="What the pin attaches to — a node id, map region, or artist.")
    metric_ref: str = Field(description="The insight metric behind the pin.")
    line: str = Field(description="The field-manual annotation.")
    dismissible_id: str = Field(description="Stable id for remembering a dismissal.")
    salience: float = Field(description="Ranking score used to pick the top pins.")


class PinsResponse(BaseModel):
    """Deterministic annotations for one canvas surface, most salient first."""

    surface: str
    pins: list[PinResource]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


_SURFACES = frozenset({"graph", "field", "galaxy"})


def _edition_resource(edition: InsightEdition) -> EditionResource:
    assert edition.id is not None
    return EditionResource(
        id=edition.id,
        edition_number=edition.edition_number,
        week_start=edition.week_start.isoformat(),
        generated_at=edition.generated_at.isoformat(),
        owned_only=edition.owned_only,
        headline=edition.headline,
        narrative=edition.narrative,
        links={
            "self": HalLink(href=f"/v1/insights/editions/{edition.id}"),
            "editions": HalLink(href="/v1/insights/editions"),
            "insights": HalLink(href="/v1/insights"),
        },
    )


@router.get(
    "/v1/insights",
    summary="Insights survey",
    description=(
        "The full insights survey in one payload: who you are as a listener "
        "(acoustic fingerprint, genre breadth, generalist-specialist score, "
        "archetype), the shape of your sound (Camelot wheel, mood quadrants, "
        "tempo, feature distributions), the history of your curation (adds over "
        "time, dormant playlists), your era profile, and a board of "
        "superlatives. Everything is measured against your own library, so the "
        "readings are always meaningful for you."
    ),
)
def insights_survey(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> InsightsResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.insights,
        lambda: compute_insights_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return InsightsResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/insights"),
            "editions": HalLink(href="/v1/insights/editions"),
            "pins": HalLink(href="/v1/insights/pins"),
            "map": HalLink(href="/v1/map/tracks"),
        },
    )


@router.get(
    "/v1/insights/editions",
    summary="Insight editions",
    description=(
        "The field journal: every frozen weekly reading, newest first. Each "
        "edition captures the headline metrics that week and the narrative of "
        "what moved since the previous one."
    ),
)
def list_editions(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> EditionCollection:
    rows = session.exec(
        select(InsightEdition)
        .where(InsightEdition.user_id == user.id)
        .where(InsightEdition.owned_only == owned_only)
        .order_by(col(InsightEdition.week_start).desc())
    ).all()
    items = [
        EditionSummary(
            id=edition.id,  # type: ignore[arg-type]
            edition_number=edition.edition_number,
            week_start=edition.week_start.isoformat(),
            generated_at=edition.generated_at.isoformat(),
            owned_only=edition.owned_only,
            line_count=len(edition.narrative),
            links={"self": HalLink(href=f"/v1/insights/editions/{edition.id}")},
        )
        for edition in rows
    ]
    return EditionCollection(
        items=items,
        total=len(items),
        links={
            "self": HalLink(href="/v1/insights/editions"),
            "compile": HalLink(href="/v1/insights/editions/compile"),
            "insights": HalLink(href="/v1/insights"),
        },
    )


@router.get(
    "/v1/insights/editions/{edition_id}",
    summary="Insight edition",
    description="One edition from the field journal, with its full narrative.",
    responses={404: {"model": ProblemDetail, "description": "Unknown edition."}},
)
def get_edition(edition_id: int, session: SessionDep, user: CurrentUserDep) -> EditionResource:
    edition = session.exec(
        select(InsightEdition)
        .where(InsightEdition.id == edition_id)
        .where(InsightEdition.user_id == user.id)
    ).first()
    if edition is None:
        raise AppError(
            404,
            "Edition not found",
            detail=f"No insight edition with id {edition_id}.",
            error_code="EDITION_NOT_FOUND",
        )
    return _edition_resource(edition)


@router.post(
    "/v1/insights/editions/compile",
    summary="Compile this week's edition",
    description=(
        "Compile (or rebuild) the current week's edition from the live "
        "insights. The first ever edition is the baseline reading; later "
        "editions diff against the previous one. Recompiling a week updates it "
        "in place. Normally the weekly scheduler runs this; the endpoint is for "
        "compiling on demand."
    ),
)
def compile_current_edition(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> EditionResource:
    edition = editions_service.compile_edition(session, user, owned_only=owned_only)
    return _edition_resource(edition)


@router.get(
    "/v1/insights/pins",
    summary="Canvas insight pins",
    description=(
        "Field-manual annotations for one canvas surface, anchored to nodes, "
        "map regions, or artists. Pins are deterministic — the same library "
        "state always yields the same ones — and each carries a stable id so "
        "the canvas can remember dismissals."
    ),
    responses={422: {"model": ProblemDetail, "description": "Unknown surface."}},
)
def insight_pins(
    session: SessionDep,
    user: CurrentUserDep,
    surface: SurfaceParam = "field",
    owned_only: OwnedOnlyParam = True,
) -> PinsResponse:
    if surface not in _SURFACES:
        raise AppError(
            422,
            "Unknown surface",
            detail=f"surface must be one of graph, field, galaxy (got {surface!r}).",
            error_code="UNKNOWN_SURFACE",
        )
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.insights,
        lambda: compute_insights_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    galaxy: dict[str, Any] = {}
    if surface == "galaxy":
        galaxy = get_or_compute(
            session,
            user,
            SnapshotKind.artist_galaxy,
            lambda: compute_artist_galaxy_payload(session, user, owned_only=owned_only),
            owned_only=owned_only,
        )
    pins_payload = compute_pins_payload(payload, galaxy, surface)
    return PinsResponse(
        **pins_payload,
        links={
            "self": HalLink(href=f"/v1/insights/pins?surface={surface}"),
            "insights": HalLink(href="/v1/insights"),
        },
    )
