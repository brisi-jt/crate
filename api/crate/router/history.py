"""Lifetime history import: review-queue listing.

The import itself runs from ``scripts/import_history.py`` (a GDPR export is a
local file drop, not an upload). This router exposes the parked review rows —
export lines that could not be resolved to a catalog track, or were skipped as
non-plays — so the state of an import is inspectable over HTTP.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from crate.deps import CurrentUserDep, SessionDep
from crate.model.enums import HistoryImportStatus
from crate.model.orm import HistoryImportReview
from crate.router.playlists import HalLink, _collection_links

router = APIRouter(tags=["history"])

LimitParam = Annotated[int, Query(ge=1, le=100, description="Page size.")]
OffsetParam = Annotated[int, Query(ge=0, description="Items to skip from the start.")]


class HistoryReviewResource(BaseModel):
    """One parked line from a lifetime history import."""

    id: int
    status: HistoryImportStatus = Field(
        description="pending (retryable), resolved (matched + ingested), or skipped (never a play)."
    )
    played_at: datetime = Field(description="When the source line says the play happened.")
    track_id: int | None = Field(
        description="The catalog track, once a re-resolution pass has matched the line."
    )
    raw: dict[str, Any] = Field(description="The verbatim export record, for re-resolution.")


class HistoryReviewCollection(BaseModel):
    items: list[HistoryReviewResource]
    total: int = Field(description="Total reviews matching the status filter, ignoring pagination.")
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.get(
    "/v1/history/import/reviews",
    summary="List history-import review rows",
    description=(
        "Export lines from a lifetime history import that did not become plays. "
        "'pending' rows had a track not yet in the library and can be resolved "
        "by a later import; 'skipped' rows were podcast episodes, local files, "
        "or zero-listen plays; 'resolved' rows were matched and ingested. "
        "Defaults to pending, the actionable backlog."
    ),
)
def list_history_reviews(
    session: SessionDep,
    user: CurrentUserDep,
    status: Annotated[
        HistoryImportStatus,
        Query(description="Which review status to list."),
    ] = HistoryImportStatus.pending,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> HistoryReviewCollection:
    total = session.exec(
        select(func.count())
        .select_from(HistoryImportReview)
        .where(HistoryImportReview.user_id == user.id)
        .where(HistoryImportReview.status == status)
    ).one()
    rows = session.exec(
        select(HistoryImportReview)
        .where(HistoryImportReview.user_id == user.id)
        .where(HistoryImportReview.status == status)
        .order_by(col(HistoryImportReview.played_at).desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        HistoryReviewResource(
            id=row.id,
            status=row.status,
            played_at=row.played_at,
            track_id=row.track_id,
            raw=row.raw,
        )
        for row in rows
        if row.id is not None
    ]
    return HistoryReviewCollection(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links(
            "/v1/history/import/reviews", limit=limit, offset=offset, total=total
        ),
    )
