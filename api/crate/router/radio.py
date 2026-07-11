"""Playlist radio endpoints: seeded listening sessions with per-item verdicts.

A radio session turns one seed — a playlist, a handful of tracks, or a genre
— into an ordered run of library material with discovery candidates
interleaved. Keeping a candidate can route it through the journaled add
path, so a radio decision is as undoable as any other playlist edit.
"""

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from crate.deps import (
    CurrentUserDep,
    RadioBuilder,
    SessionDep,
    WriterFactoryDep,
    get_radio_builder,
)
from crate.errors import AppError, ProblemDetail
from crate.model.enums import (
    CandidateStatus,
    FeedbackAction,
    RadioItemFeedback,
    RadioItemKind,
    RadioSeedKind,
)
from crate.model.orm import DiscoveryCandidate, RadioItem, RadioSession, SuggestionFeedback, User
from crate.router.playlists import HalLink
from crate.services.discovery.service import accept_candidate
from crate.services.radio.service import (
    DEFAULT_DISCOVERY_RATIO,
    DEFAULT_LENGTH,
    load_radio_items,
)

router = APIRouter(tags=["radio"])

RadioBuilderDep = Annotated[RadioBuilder, Depends(get_radio_builder)]


class RadioFeedbackAction(StrEnum):
    """A verdict on one radio item."""

    keep = "keep"
    skip = "skip"


# ------------------------------------------------------------------ bodies


class RadioCreateBody(BaseModel):
    playlist_id: int | None = Field(
        default=None, description="Seed the session from one playlist's sound."
    )
    track_ids: list[int] | None = Field(
        default=None,
        description="Seed from specific tracks — the session gathers the "
        "library's nearest material to their combined sound.",
    )
    genre_seed: str | None = Field(
        default=None,
        description="Seed from a genre: library tracks by the genre's "
        "artists, plus matching unreviewed candidates.",
    )
    length: int = Field(
        default=DEFAULT_LENGTH, ge=5, le=50, description="Target session length in tracks."
    )
    discovery_ratio: float = Field(
        default=DEFAULT_DISCOVERY_RATIO,
        ge=0.0,
        le=0.5,
        description="Fraction of the session drawn from discovery candidates "
        "(default one in five).",
    )


class RadioFeedbackBody(BaseModel):
    action: RadioFeedbackAction = Field(
        description="keep marks the track a keeper; skip passes on it. Both "
        "feed the discovery ranker when the item is a candidate."
    )
    add_to_playlist_id: int | None = Field(
        default=None,
        description="With keep on a candidate: also add the track to this "
        "playlist through the journaled write path (undoable).",
    )


# ---------------------------------------------------------------- responses


class RadioItemResource(BaseModel):
    """One positioned entry in a radio session."""

    id: int
    position: int
    kind: RadioItemKind = Field(description="Library track or interleaved discovery candidate.")
    track_id: int | None
    candidate_id: int | None
    title: str
    artist: str
    spotify_id: str | None
    preview_url: str | None = Field(
        description="30-second audio preview; null when none could be found."
    )
    tempo: float | None = Field(description="BPM readout, when known.")
    camelot: str | None = Field(description="Camelot wheel position (e.g. 8A), when known.")
    feedback: RadioItemFeedback | None = Field(description="The verdict recorded, if any.")
    journal_id: int | None = Field(
        description="Set when keeping the item added it to a playlist (undo target)."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class RadioSummary(BaseModel):
    """Session progress rollup."""

    kept: int
    skipped: int
    added: int = Field(description="Kept candidates that were added to a playlist.")
    pending: int = Field(description="Items still awaiting a verdict.")


class RadioSessionResource(BaseModel):
    """One radio session with its ordered items."""

    id: int
    seed_kind: RadioSeedKind
    seed_playlist_id: int | None
    seed_genre: str | None
    label: str = Field(description="Human-readable seed description.")
    discovery_ratio: float
    items: list[RadioItemResource]
    summary: RadioSummary
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ------------------------------------------------------------------ helpers


def _item_resource(radio_id: int, item: RadioItem) -> RadioItemResource:
    assert item.id is not None
    links = {
        "feedback": HalLink(href=f"/v1/radio/{radio_id}/items/{item.id}/feedback"),
    }
    if item.journal_id is not None:
        links["journal"] = HalLink(href=f"/v1/journal/{item.journal_id}")
        links["undo"] = HalLink(href=f"/v1/journal/{item.journal_id}/undo")
    if item.spotify_id and not item.spotify_id.startswith("fake-"):
        links["spotify"] = HalLink(href=f"https://open.spotify.com/track/{item.spotify_id}")
    return RadioItemResource(
        id=item.id,
        position=item.position,
        kind=item.kind,
        track_id=item.track_id,
        candidate_id=item.candidate_id,
        title=item.title,
        artist=item.artist,
        spotify_id=item.spotify_id,
        preview_url=item.preview_url,
        tempo=item.tempo,
        camelot=item.camelot,
        feedback=item.feedback,
        journal_id=item.journal_id,
        links=links,
    )


def _session_resource(session: Session, radio: RadioSession) -> RadioSessionResource:
    assert radio.id is not None
    items = load_radio_items(session, radio)
    kept = sum(1 for item in items if item.feedback == RadioItemFeedback.kept)
    skipped = sum(1 for item in items if item.feedback == RadioItemFeedback.skipped)
    added = sum(1 for item in items if item.journal_id is not None)
    links = {"self": HalLink(href=f"/v1/radio/{radio.id}")}
    if radio.seed_playlist_id is not None:
        links["playlist"] = HalLink(href=f"/v1/playlists/{radio.seed_playlist_id}")
    return RadioSessionResource(
        id=radio.id,
        seed_kind=radio.seed_kind,
        seed_playlist_id=radio.seed_playlist_id,
        seed_genre=radio.seed_genre,
        label=radio.label,
        discovery_ratio=radio.discovery_ratio,
        items=[_item_resource(radio.id, item) for item in items],
        summary=RadioSummary(
            kept=kept, skipped=skipped, added=added, pending=len(items) - kept - skipped
        ),
        links=links,
    )


def _require_radio(session: Session, user: User, radio_id: int) -> RadioSession:
    radio = session.get(RadioSession, radio_id)
    if radio is None or radio.user_id != user.id:
        raise AppError(
            404,
            "Radio session not found",
            detail=f"No radio session with id {radio_id}.",
            error_code="RADIO_NOT_FOUND",
        )
    return radio


# ----------------------------------------------------------------- endpoints


@router.post(
    "/v1/radio",
    status_code=201,
    summary="Start a radio session",
    description=(
        "Generates an ordered listening run from one seed: a playlist, a set "
        "of tracks, or a genre. Library material is ordered for harmonic and "
        "tempo flow; discovery candidates are interleaved at a steady cadence "
        "(configurable, default one in five). The session persists — reload "
        "it any time to continue."
    ),
    responses={
        400: {"model": ProblemDetail, "description": "Zero or multiple seeds given."},
        404: {"model": ProblemDetail, "description": "Unknown playlist, track, or genre."},
        409: {"model": ProblemDetail, "description": "The seed has nothing to play."},
    },
)
async def create_radio(
    body: RadioCreateBody,
    session: SessionDep,
    user: CurrentUserDep,
    builder: RadioBuilderDep,
) -> RadioSessionResource:
    seeds_given = sum(
        value is not None for value in (body.playlist_id, body.track_ids, body.genre_seed)
    )
    if seeds_given != 1:
        raise AppError(
            400,
            "Radio needs one seed",
            detail="Seed a radio with exactly one of playlist_id, track_ids, or genre_seed.",
            error_code="RADIO_SEED_INVALID",
        )
    radio = await builder(
        session,
        user,
        body.playlist_id,
        body.track_ids,
        body.genre_seed,
        body.length,
        body.discovery_ratio,
    )
    return _session_resource(session, radio)


@router.get(
    "/v1/radio/{radio_id}",
    summary="Read a radio session",
    description="The session's ordered items, recorded verdicts, and progress rollup.",
    responses={404: {"model": ProblemDetail, "description": "Unknown radio session."}},
)
def get_radio(
    radio_id: int,
    session: SessionDep,
    user: CurrentUserDep,
) -> RadioSessionResource:
    radio = _require_radio(session, user, radio_id)
    return _session_resource(session, radio)


@router.post(
    "/v1/radio/{radio_id}/items/{item_id}/feedback",
    summary="Record a verdict on a radio item",
    description=(
        "Marks the item kept or skipped — each item takes one verdict. On a "
        "discovery candidate the verdict also feeds the suggestion ranker; "
        "keep with add_to_playlist_id routes the track through the journaled "
        "add path and returns the undo link."
    ),
    responses={
        400: {
            "model": ProblemDetail,
            "description": "add_to_playlist_id on a track that is already in the library.",
        },
        404: {"model": ProblemDetail, "description": "Unknown session or item."},
        409: {"model": ProblemDetail, "description": "The item already has a verdict."},
    },
)
async def post_radio_feedback(
    radio_id: int,
    item_id: int,
    body: RadioFeedbackBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> RadioItemResource:
    radio = _require_radio(session, user, radio_id)
    item = session.get(RadioItem, item_id)
    if item is None or item.session_id != radio.id:
        raise AppError(
            404,
            "Radio item not found",
            detail=f"No item {item_id} in radio session {radio_id}.",
            error_code="RADIO_ITEM_NOT_FOUND",
        )
    if item.feedback is not None:
        raise AppError(
            409,
            "Item already reviewed",
            detail=f"Item {item_id} is already marked {item.feedback.value}.",
            error_code="RADIO_ITEM_ALREADY_REVIEWED",
        )
    if body.add_to_playlist_id is not None and (
        item.kind != RadioItemKind.discovery or body.action != RadioFeedbackAction.keep
    ):
        raise AppError(
            400,
            "Only kept candidates can be added",
            detail="add_to_playlist_id applies to keep verdicts on discovery items — "
            "library tracks are already in the library.",
            error_code="RADIO_ADD_NOT_CANDIDATE",
        )

    candidate: DiscoveryCandidate | None = None
    if item.kind == RadioItemKind.discovery and item.candidate_id is not None:
        candidate = session.get(DiscoveryCandidate, item.candidate_id)

    if body.action == RadioFeedbackAction.keep:
        item.feedback = RadioItemFeedback.kept
        if candidate is not None and body.add_to_playlist_id is not None:
            if candidate.status != CandidateStatus.resolved:
                raise AppError(
                    409,
                    "Suggestion not reviewable",
                    detail=f"Candidate {candidate.id} is {candidate.status.value} — it "
                    "can no longer be added from this session.",
                    error_code="SUGGESTION_NOT_REVIEWABLE",
                )
            candidate.playlist_id = body.add_to_playlist_id
            session.add(candidate)
            async with writer_factory(session, user) as writer:
                _, journal_id = await accept_candidate(session, user, candidate, writer)
            item.journal_id = journal_id
        elif candidate is not None and candidate.status == CandidateStatus.resolved:
            # Signal-only keep: count toward the artist's accept tally without
            # consuming the candidate — it stays reviewable in the deck.
            session.add(
                SuggestionFeedback(
                    user_id=user.id,
                    candidate_id=candidate.id,
                    playlist_id=candidate.playlist_id,
                    artist=candidate.artist,
                    action=FeedbackAction.accept,
                )
            )
    else:
        item.feedback = RadioItemFeedback.skipped
        if candidate is not None and candidate.status == CandidateStatus.resolved:
            session.add(
                SuggestionFeedback(
                    user_id=user.id,
                    candidate_id=candidate.id,
                    playlist_id=candidate.playlist_id,
                    artist=candidate.artist,
                    action=FeedbackAction.skip,
                )
            )

    session.add(item)
    session.commit()
    session.refresh(item)
    assert radio.id is not None
    return _item_resource(radio.id, item)
