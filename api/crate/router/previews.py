"""Preview refresh: hand the client a fresh, playable preview URL.

Deezer preview URLs expire ~20 minutes after issue, so the deck and radio hit
403s at play time. The client calls this to re-resolve one entity's preview.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crate.deps import CurrentUserDep, PreviewRefresher, SessionDep, get_preview_refresher
from crate.errors import AppError, ProblemDetail
from crate.services.previews.refresh import PreviewTargetNotFound, PreviewUnresolvable

router = APIRouter(prefix="/v1/previews", tags=["previews"])

PreviewRefresherDep = Annotated[PreviewRefresher, Depends(get_preview_refresher)]


class HalLink(BaseModel):
    href: str


class PreviewRefreshBody(BaseModel):
    """Exactly one target identifier — the entity whose preview to refresh."""

    track_id: int | None = Field(
        default=None, description="Refresh the preview for a catalog track."
    )
    candidate_id: int | None = Field(
        default=None, description="Refresh the preview for a discovery candidate."
    )
    radio_item_id: int | None = Field(
        default=None, description="Refresh the preview for a radio-session item."
    )


class PreviewRefreshResult(BaseModel):
    """A fresh, playable preview URL and how long it stays valid."""

    preview_url: str = Field(description="A freshly-resolved 30-second preview URL.")
    expires_hint_seconds: int = Field(
        description="Roughly how long the URL stays valid; refresh again before it lapses."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.post(
    "/refresh",
    summary="Refresh an expired preview URL",
    description=(
        "Re-resolves a fresh 30-second preview URL for one track, discovery "
        "candidate, or radio item, bypassing the cached (likely expired) URL "
        "and persisting the new one. Deezer previews lapse about 20 minutes "
        "after they are issued, so the deck and radio call this on a 403 at "
        "play time. Provide exactly one of track_id, candidate_id, or "
        "radio_item_id. Returns 404 when no fresh preview exists for the entity."
    ),
    responses={
        400: {"model": ProblemDetail, "description": "Not exactly one target id was given."},
        404: {
            "model": ProblemDetail,
            "description": "The entity does not exist, or has no resolvable preview.",
        },
    },
)
async def refresh_preview_endpoint(
    body: PreviewRefreshBody,
    session: SessionDep,
    user: CurrentUserDep,
    refresher: PreviewRefresherDep,
) -> PreviewRefreshResult:
    given = [i for i in (body.track_id, body.candidate_id, body.radio_item_id) if i is not None]
    if len(given) != 1:
        raise AppError(
            400,
            "One preview target required",
            detail="Provide exactly one of track_id, candidate_id, or radio_item_id.",
            error_code="PREVIEW_TARGET_INVALID",
        )
    try:
        refreshed = await refresher(
            session,
            user,
            track_id=body.track_id,
            candidate_id=body.candidate_id,
            radio_item_id=body.radio_item_id,
        )
    except PreviewTargetNotFound as exc:
        raise AppError(
            404,
            "Preview target not found",
            detail=f"No {exc.kind} with id {exc.entity_id} for this account.",
            error_code="PREVIEW_TARGET_NOT_FOUND",
        ) from exc
    except PreviewUnresolvable as exc:
        raise AppError(
            404,
            "No resolvable preview",
            detail=f"No preview audio could be found for {exc.kind} {exc.entity_id}.",
            error_code="PREVIEW_UNRESOLVABLE",
        ) from exc
    return PreviewRefreshResult(
        preview_url=refreshed.preview_url,
        expires_hint_seconds=refreshed.expires_hint_seconds,
        links={"self": HalLink(href="/v1/previews/refresh")},
    )
