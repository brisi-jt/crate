"""Weekly digest endpoints: the inbox's reading list.

A digest summarizes one Monday-to-Monday week — new suggestions, the best
unreviewed candidates, library changes, listening notes, and frontier
movement. Items carry deep-link targets so a reader can jump straight from
an entry to the playlist, candidate queue, or genre it describes.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlmodel import col, func, select

from crate.deps import CurrentUserDep, SessionDep
from crate.errors import AppError, ProblemDetail
from crate.model.enums import DigestSection
from crate.model.orm import Digest, DigestItem, utcnow
from crate.router.playlists import HalLink, _collection_links
from crate.services.digest.service import generate_digest, week_start_for

router = APIRouter(tags=["digests"])

LimitParam = Annotated[int, Query(ge=1, le=100, description="Page size.")]
OffsetParam = Annotated[int, Query(ge=0, description="Items to skip from the start.")]


class DigestItemResource(BaseModel):
    """One digest entry with its deep-link targets."""

    id: int
    section: DigestSection = Field(description="Which part of the digest the item belongs to.")
    title: str
    body: str | None
    playlist_id: int | None = Field(
        description="Playlist the item points at, when it concerns one."
    )
    candidate_id: int | None = Field(
        description="Suggestion the item points at — open its playlist's queue to review it."
    )
    genre: str | None = Field(description="Genre the item points at, for frontier entries.")
    extra: dict[str, Any] | None = Field(
        description="Section-specific readouts: counts, fit scores, play totals."
    )


class DigestResource(BaseModel):
    """One weekly digest with its items in reading order."""

    id: int
    week_start: datetime = Field(description="Monday the covered week starts on (UTC).")
    generated_at: datetime
    read_at: datetime | None = Field(description="When the digest was opened; null = unread.")
    items: list[DigestItemResource]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class DigestSummaryResource(BaseModel):
    """A digest as listed in the inbox."""

    id: int
    week_start: datetime
    generated_at: datetime
    read_at: datetime | None = Field(description="When the digest was opened; null = unread.")
    item_count: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class DigestCollection(BaseModel):
    items: list[DigestSummaryResource]
    total: int = Field(description="Total digests on file, ignoring pagination.")
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class GenerateDigestBody(BaseModel):
    week_start: datetime | None = Field(
        default=None,
        description="Monday of the week to digest; omit for the current week to date.",
    )


def _require_digest(session: SessionDep, user_id: int, digest_id: int) -> Digest:
    digest = session.get(Digest, digest_id)
    if digest is None or digest.user_id != user_id:
        raise AppError(
            404,
            "Digest not found",
            detail=f"No digest with id {digest_id}.",
            error_code="DIGEST_NOT_FOUND",
        )
    return digest


def _digest_resource(session: SessionDep, digest: Digest) -> DigestResource:
    assert digest.id is not None
    items = session.exec(
        select(DigestItem)
        .where(DigestItem.digest_id == digest.id)
        .order_by(col(DigestItem.position))
    ).all()
    return DigestResource(
        id=digest.id,
        week_start=digest.week_start,
        generated_at=digest.generated_at,
        read_at=digest.read_at,
        items=[
            DigestItemResource(
                id=item.id or 0,
                section=item.section,
                title=item.title,
                body=item.body,
                playlist_id=item.playlist_id,
                candidate_id=item.candidate_id,
                genre=item.genre,
                extra=item.extra,
            )
            for item in items
        ],
        links={
            "self": HalLink(href=f"/v1/digests/{digest.id}"),
            "read": HalLink(href=f"/v1/digests/{digest.id}/read"),
            "digests": HalLink(href="/v1/digests"),
        },
    )


@router.get(
    "/v1/digests",
    summary="List digests",
    description=(
        "Weekly digests, newest week first. read_at is null until a digest "
        "has been opened — an unread digest is the inbox's cue."
    ),
)
def list_digests(
    session: SessionDep,
    user: CurrentUserDep,
    limit: LimitParam = 20,
    offset: OffsetParam = 0,
) -> DigestCollection:
    assert user.id is not None
    total = session.exec(
        select(func.count()).select_from(Digest).where(Digest.user_id == user.id)
    ).one()
    digests = session.exec(
        select(Digest)
        .where(Digest.user_id == user.id)
        .order_by(col(Digest.week_start).desc())
        .limit(limit)
        .offset(offset)
    ).all()
    counts: dict[int, int] = {}
    ids = [digest.id for digest in digests if digest.id is not None]
    if ids:
        rows = session.exec(
            select(DigestItem.digest_id, func.count())
            .where(col(DigestItem.digest_id).in_(ids))
            .group_by(col(DigestItem.digest_id))
        ).all()
        counts = dict(rows)
    return DigestCollection(
        items=[
            DigestSummaryResource(
                id=digest.id or 0,
                week_start=digest.week_start,
                generated_at=digest.generated_at,
                read_at=digest.read_at,
                item_count=counts.get(digest.id or 0, 0),
                links={"self": HalLink(href=f"/v1/digests/{digest.id}")},
            )
            for digest in digests
        ],
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links(
            "/v1/digests",
            limit=limit,
            offset=offset,
            total=total,
            extra={"generate": "/v1/digest/generate"},
        ),
    )


@router.get(
    "/v1/digests/{digest_id}",
    summary="Read a digest",
    description="One digest with its items in reading order, deep-link targets included.",
    responses={404: {"model": ProblemDetail, "description": "Unknown digest."}},
)
def get_digest(
    digest_id: int,
    session: SessionDep,
    user: CurrentUserDep,
) -> DigestResource:
    assert user.id is not None
    digest = _require_digest(session, user.id, digest_id)
    return _digest_resource(session, digest)


@router.post(
    "/v1/digests/{digest_id}/read",
    summary="Mark a digest read",
    description=(
        "Stamps read_at so the inbox stops flagging the digest as unread. "
        "Reading an already-read digest keeps the original timestamp."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown digest."}},
)
def mark_digest_read(
    digest_id: int,
    session: SessionDep,
    user: CurrentUserDep,
) -> DigestResource:
    assert user.id is not None
    digest = _require_digest(session, user.id, digest_id)
    if digest.read_at is None:
        digest.read_at = utcnow()
        session.add(digest)
        session.commit()
        session.refresh(digest)
    return _digest_resource(session, digest)


@router.post(
    "/v1/digest/generate",
    summary="Generate a digest now",
    description=(
        "Builds (or rebuilds) the digest for a week without waiting for the "
        "Monday schedule. Defaults to the current week so far; regenerating "
        "an existing week replaces its items and marks it unread again."
    ),
)
def generate_digest_now(
    body: GenerateDigestBody,
    session: SessionDep,
    user: CurrentUserDep,
) -> DigestResource:
    assert user.id is not None
    week_start = week_start_for(body.week_start) if body.week_start else None
    digest = generate_digest(session, user, week_start=week_start)
    return _digest_resource(session, digest)
