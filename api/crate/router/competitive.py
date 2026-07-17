"""Competitor-parity read surfaces + the flow-arc reorder (F1, F3, F4, F5, F6).

Five features that close gaps against stats.fm / Obscurify / Chosic / Sort Your
Music, each grounded in data crate already owns (play_events, ENAO genre ranks,
self-derived features, top-items history):

- F1 GET /v1/listening/dashboard       — listening rhythm (clocks, plays,
                                          minutes, streaks), with a play range.
- F3 GET /v1/obscurity                  — library + per-playlist niche-ness.
- F5 GET /v1/taste/drift                — now-vs-past-self fingerprint drift.
- F6 GET /v1/quality/playlists          — per-playlist quality breakdown.
- F4 GET  /v1/playlists/{id}/flow/arc         — a proposed mood-arc reorder.
     POST /v1/playlists/{id}/flow/arc/apply    — apply it through the journal.

Every new user-facing number carries a stable metric_ref for the web to attach
an explain to. F4's apply is the ONLY write here and rides the existing
MutationService.reorder — no parallel write path; undo restores the prior order.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from crate.deps import CurrentUserDep, SessionDep, WriterFactoryDep
from crate.errors import ProblemDetail
from crate.model.enums import ListeningRange
from crate.router.analytics import HalLink, OwnedOnlyParam, _require_playlist
from crate.services.competitive import engine
from crate.services.competitive.flow_arc import ArcMood
from crate.services.mutations.service import MutationService

router = APIRouter(tags=["competitive"])


RangeParam = Annotated[
    ListeningRange,
    Query(
        description=(
            "Which plays to include. 'all_time' (default) spans everything, "
            "including any lifetime GDPR history imported into the past. "
            "'since_crate' restricts to plays captured live from Spotify's "
            "recently-played feed, excluding imported history."
        )
    ),
]


# ----------------------------------------------------------- F1 rhythm dashboard


@router.get(
    "/v1/listening/dashboard",
    summary="Listening-rhythm dashboard",
    description=(
        "When and how much the account listens: hour-of-day and weekday clocks, "
        "total plays and distinct tracks, minutes listened (exact where a play "
        "records its duration, estimated otherwise), listening streaks, and the "
        "most-played tracks. Pass range=since_crate to exclude imported history."
    ),
)
def listening_dashboard(
    session: SessionDep,
    user: CurrentUserDep,
    range: RangeParam = ListeningRange.all_time,
) -> dict[str, Any]:
    payload = engine.build_rhythm(session, user, range_=range.value)
    payload["_links"] = {
        "self": HalLink(href="/v1/listening/dashboard").model_dump(),
        "recent": HalLink(href="/v1/listening/recent").model_dump(),
    }
    return payload


# ------------------------------------------------------------------ F3 obscurity


@router.get(
    "/v1/obscurity",
    summary="Obscurity score",
    description=(
        "How niche the library is, and each playlist within it, on a 0 "
        "(mainstream) to 1 (obscure) scale grounded in the Every Noise genre "
        "popularity ordering. Playlists are listed most-obscure first. A "
        "Last.fm listener-count refinement is a pending upgrade — the score "
        "reports its source and does not fabricate a listener figure."
    ),
)
def obscurity(
    session: SessionDep,
    user: CurrentUserDep,
    owned_only: OwnedOnlyParam = True,
) -> dict[str, Any]:
    payload = engine.build_obscurity(session, user, owned_only=owned_only)
    payload["_links"] = {"self": HalLink(href="/v1/obscurity").model_dump()}
    return payload


# ---------------------------------------------------------------------- F5 drift


@router.get(
    "/v1/taste/drift",
    summary="Taste drift vs a past self",
    description=(
        "How the library's current sound compares to a past top-tracks "
        "snapshot: the available snapshot timeline plus, when a snapshot_id is "
        "given, the per-axis fingerprint delta (now minus then) and how far "
        "taste has moved. Only track snapshots are comparable; artist snapshots "
        "appear in the timeline for context."
    ),
)
def taste_drift(
    session: SessionDep,
    user: CurrentUserDep,
    snapshot_id: Annotated[
        int | None,
        Query(
            description="A snapshot_id from the timeline to compare against; "
            "omit for the timeline only."
        ),
    ] = None,
    owned_only: OwnedOnlyParam = True,
) -> dict[str, Any]:
    payload = engine.build_drift(session, user, snapshot_id=snapshot_id, owned_only=owned_only)
    payload["_links"] = {"self": HalLink(href="/v1/taste/drift").model_dump()}
    return payload


# -------------------------------------------------------------------- F6 quality


@router.get(
    "/v1/quality/playlists",
    summary="Per-playlist quality score",
    description=(
        "A 0..1 quality score per playlist, blended from four explainable "
        "sub-scores — cohesion (sound tightness), uniqueness (no duplicates), "
        "freshness (recently tended), and flow (smooth track-to-track "
        "transitions). Each sub-score carries its own reference for a "
        "per-limb explanation. Playlists are listed highest-quality first."
    ),
)
def playlist_quality(
    session: SessionDep,
    user: CurrentUserDep,
    owned_only: OwnedOnlyParam = True,
) -> dict[str, Any]:
    payload = engine.build_quality(session, user, owned_only=owned_only)
    payload["_links"] = {"self": HalLink(href="/v1/quality/playlists").model_dump()}
    return payload


# ------------------------------------------------------------------ F4 flow arc

MoodParam = Annotated[
    ArcMood,
    Query(
        description=(
            "The energy trajectory to shape the order toward: rising (builds), "
            "falling (winds down), or peak (rises to a mid-set apex then falls)."
        )
    ),
]


class ArcApplyBody(BaseModel):
    order: list[int] = Field(
        min_length=1,
        description="The track ids in the new play order — the array the arc "
        "preview returned as suggested_order.",
    )


@router.get(
    "/v1/playlists/{playlist_id}/flow/arc",
    summary="Mood-arc reorder preview",
    description=(
        "A proposed reorder that shapes the playlist's energy toward a chosen "
        "arc and separates same-artist tracks, on top of the existing "
        "key/tempo flow. Read-only — it returns the suggested order plus the "
        "current and suggested flow scores; apply it via the arc apply "
        "endpoint to write it through the journal."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown playlist."}},
)
def flow_arc_preview(
    playlist_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    mood: MoodParam = ArcMood.rising,
    owned_only: OwnedOnlyParam = True,
) -> dict[str, Any]:
    _require_playlist(session, user, playlist_id)
    preview = engine.build_arc_preview(
        session, user, playlist_id, mood=mood.value, owned_only=owned_only
    )
    if preview is None:
        # Below the three-track floor (or no reorderable tracks): a quiet empty
        # preview, not an error — the playlist simply can't be arc-sequenced.
        preview = {
            "playlist_id": playlist_id,
            "mood": mood.value,
            "suggested_order": [],
            "current_flow": None,
            "suggested_flow": None,
            "adjacent_artist_repeats": 0,
        }
    preview["_links"] = {
        "self": HalLink(href=f"/v1/playlists/{playlist_id}/flow/arc").model_dump(),
        "apply": HalLink(href=f"/v1/playlists/{playlist_id}/flow/arc/apply").model_dump(),
    }
    return preview


ARC_WRITE_ERRORS: dict[int | str, dict] = {
    404: {"model": ProblemDetail, "description": "Unknown playlist."},
    409: {"model": ProblemDetail, "description": "Order no longer matches the playlist."},
    502: {
        "model": ProblemDetail,
        "description": "Spotify write failed; the journal records the prior order.",
    },
}


class ArcApplyResult(BaseModel):
    journal_id: int
    status: str
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.post(
    "/v1/playlists/{playlist_id}/flow/arc/apply",
    summary="Apply a mood-arc reorder",
    description=(
        "Writes a mood-arc order (from the arc preview) as the playlist's new "
        "track order, through the journaled write system — undoable with one "
        "call, and it preserves each track's added_at. Rejected (409) when the "
        "submitted order no longer matches the playlist's current tracks."
    ),
    responses=ARC_WRITE_ERRORS,
)
async def flow_arc_apply(
    playlist_id: int,
    body: ArcApplyBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> ArcApplyResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.reorder(playlist_id, body.order)
    return ArcApplyResult(
        journal_id=journal.id,
        status=journal.status.value,
        links={
            "journal": HalLink(href=f"/v1/journal/{journal.id}"),
            "undo": HalLink(href=f"/v1/journal/{journal.id}/undo"),
        },
    )
