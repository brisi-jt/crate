"""Playlist write endpoints: single ops, bulk algebra, and the undo journal.

Every mutation is journaled before it touches Spotify and can be reverted via
POST /v1/journal/{id}/undo. Bulk changes are two-step: preview computes and
stores the exact delta, apply replays it verbatim (409 when the library moved
in between).
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlmodel import col, select

from crate.deps import CurrentUserDep, SessionDep, WriterFactoryDep
from crate.errors import AppError, ProblemDetail
from crate.model.enums import BulkOperation, MutationOpType, MutationStatus
from crate.model.orm import MutationJournal, OpPreview, Playlist, PlaylistTrack
from crate.router.playlists import HalLink, _collection_links
from crate.services.mutations.algebra import build_preview
from crate.services.mutations.service import MutationService

router = APIRouter(tags=["writes"])


# ------------------------------------------------------------------ bodies


class AddTracksBody(BaseModel):
    track_ids: list[int] = Field(
        min_length=1, description="Track ids (from the track catalog) to add."
    )
    position: int | None = Field(
        default=None,
        ge=0,
        description="0-based insert position; omit to append at the end.",
    )


class RemoveTracksBody(BaseModel):
    positions: list[int] = Field(
        min_length=1,
        description="0-based positions to remove — positions, not track ids, so "
        "a single occurrence of a duplicated track can be targeted.",
    )


class CreatePlaylistBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=300)


class UpdatePlaylistBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "UpdatePlaylistBody":
        if self.name is None and self.description is None:
            raise ValueError("provide a name and/or a description")
        return self


class ReorderBody(BaseModel):
    order: list[int] = Field(
        min_length=1,
        description="Every track id of the playlist in the desired play order — "
        "the shape /v1/playlists/{id}/flow returns as suggested_order.",
    )


class PreviewBody(BaseModel):
    operation: BulkOperation
    source_ids: list[int] = Field(min_length=1, description="Source playlist ids.")
    target_id: int | None = Field(
        default=None, description="Existing playlist receiving the result."
    )
    new_playlist_name: str | None = Field(
        default=None,
        max_length=200,
        description="Create a playlist with this name as the target instead.",
    )


class ApplyBody(BaseModel):
    preview_id: int


# ---------------------------------------------------------------- responses


class MutationResult(BaseModel):
    """Outcome of a single journaled write."""

    journal_id: int = Field(description="Journal entry recording this mutation.")
    status: MutationStatus
    playlist_id: int
    track_count: int = Field(description="Tracks in the playlist after the write.")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class CreatedPlaylistResource(BaseModel):
    id: int
    spotify_id: str
    name: str
    description: str | None


class CreatePlaylistResult(BaseModel):
    """A playlist created on Spotify and registered locally."""

    journal_id: int
    status: MutationStatus
    playlist: CreatedPlaylistResource
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class ManifestTrackRef(BaseModel):
    track_id: int
    spotify_id: str
    name: str
    artist: str = ""


class ManifestRemoveRef(ManifestTrackRef):
    position: int = Field(description="0-based position the removal targets.")


class ManifestEntry(BaseModel):
    playlist_id: int | None = Field(description="Null when the target is a new playlist.")
    playlist_name: str
    new: bool = Field(description="True when apply will create this playlist.")
    adds: list[ManifestTrackRef]
    removes: list[ManifestRemoveRef]


class ManifestSummary(BaseModel):
    adds: int
    removes: int
    playlists: int


class Manifest(BaseModel):
    entries: list[ManifestEntry]
    summary: ManifestSummary


class PreviewResource(BaseModel):
    """A stored dry run: the exact delta apply will perform."""

    preview_id: int
    operation: BulkOperation
    manifest: Manifest
    created_at: datetime
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class ApplyEntryResult(BaseModel):
    playlist_id: int | None
    name: str
    status: str = Field(description="applied or failed.")
    error: str | None = None


class ApplyResult(BaseModel):
    """Outcome of replaying a previewed delta."""

    journal_id: int
    status: MutationStatus = Field(
        description="applied when every playlist succeeded; partial when some "
        "failed — the journal keeps per-playlist results and undo restores "
        "whatever did apply."
    )
    results: list[ApplyEntryResult]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class JournalEntryResource(BaseModel):
    """One recorded mutation."""

    id: int
    op_type: MutationOpType
    status: MutationStatus
    summary: str = Field(description="Human-readable one-liner, e.g. 'Add · Song → Gym'.")
    created_at: datetime
    undone_at: datetime | None
    detail: dict[str, Any] = Field(
        description="The full recorded payload: playlist, tracks, per-playlist results."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class JournalCollection(BaseModel):
    items: list[JournalEntryResource]
    total: int
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class UndoResult(BaseModel):
    """Outcome of reverting a journal entry."""

    journal_id: int
    status: MutationStatus
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ------------------------------------------------------------------ helpers


def _track_count(session: SessionDep, playlist_id: int) -> int:
    return session.exec(
        select(func.count())
        .select_from(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
    ).one()


def _mutation_links(journal: MutationJournal, playlist_id: int | None = None) -> dict[str, HalLink]:
    links = {
        "journal": HalLink(href=f"/v1/journal/{journal.id}"),
        "undo": HalLink(href=f"/v1/journal/{journal.id}/undo"),
    }
    if playlist_id is not None:
        links["playlist"] = HalLink(href=f"/v1/playlists/{playlist_id}")
        links["tracks"] = HalLink(href=f"/v1/playlists/{playlist_id}/tracks")
    return links


def _mutation_result(
    session: SessionDep, journal: MutationJournal, playlist_id: int
) -> MutationResult:
    return MutationResult(
        journal_id=journal.id,
        status=journal.status,
        playlist_id=playlist_id,
        track_count=_track_count(session, playlist_id),
        links=_mutation_links(journal, playlist_id),
    )


WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "Unknown playlist or track."},
    409: {
        "model": ProblemDetail,
        "description": "The playlist changed underneath the request, or Spotify isn't connected.",
    },
    502: {
        "model": ProblemDetail,
        "description": "Spotify rejected the write mid-way. The journal entry "
        "records the previous state — undo restores it.",
    },
}


# ------------------------------------------------------------- single ops


@router.post(
    "/v1/playlists/{playlist_id}/tracks",
    summary="Add tracks to a playlist",
    description=(
        "Adds tracks at the end of the playlist (or at position). The change "
        "is journaled first, applied to Spotify, then mirrored locally — undo "
        "it any time via the journal link in the response."
    ),
    responses=WRITE_ERRORS,
)
async def add_tracks(
    playlist_id: int,
    body: AddTracksBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> MutationResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.add_tracks(playlist_id, body.track_ids, position=body.position)
    return _mutation_result(session, journal, playlist_id)


@router.delete(
    "/v1/playlists/{playlist_id}/tracks",
    summary="Remove tracks from a playlist",
    description=(
        "Removes the entries at the given positions. Positions target one "
        "occurrence each, so duplicated tracks can be trimmed precisely. "
        "Journaled and undoable."
    ),
    responses=WRITE_ERRORS,
)
async def remove_tracks(
    playlist_id: int,
    body: RemoveTracksBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> MutationResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.remove_tracks(playlist_id, body.positions)
    return _mutation_result(session, journal, playlist_id)


@router.post(
    "/v1/playlists",
    status_code=201,
    summary="Create a playlist",
    description="Creates a private playlist on Spotify and registers it locally.",
    responses=WRITE_ERRORS,
)
async def create_playlist(
    body: CreatePlaylistBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> CreatePlaylistResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.create_playlist(body.name, body.description)
    playlist = session.get(Playlist, journal.payload["playlist_id"])
    assert playlist is not None
    return CreatePlaylistResult(
        journal_id=journal.id,
        status=journal.status,
        playlist=CreatedPlaylistResource(
            id=playlist.id,
            spotify_id=playlist.spotify_id,
            name=playlist.name,
            description=playlist.description,
        ),
        links=_mutation_links(journal, playlist.id),
    )


@router.patch(
    "/v1/playlists/{playlist_id}",
    summary="Rename a playlist or edit its description",
    description="Updates the given fields on Spotify and locally; omitted fields keep "
    "their value. Journaled and undoable.",
    responses=WRITE_ERRORS,
)
async def update_playlist(
    playlist_id: int,
    body: UpdatePlaylistBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> MutationResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.rename_playlist(
            playlist_id, name=body.name, description=body.description
        )
    return _mutation_result(session, journal, playlist_id)


@router.put(
    "/v1/playlists/{playlist_id}/order",
    summary="Reorder a playlist",
    description=(
        "Applies a full new play order — the exact array "
        "/v1/playlists/{id}/flow returns as suggested_order. Rejected (409) "
        "when the submitted order no longer matches the playlist's current "
        "tracks."
    ),
    responses=WRITE_ERRORS,
)
async def reorder_playlist(
    playlist_id: int,
    body: ReorderBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> MutationResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.reorder(playlist_id, body.order)
    return _mutation_result(session, journal, playlist_id)


# ------------------------------------------------------------- bulk algebra


@router.post(
    "/v1/ops/preview",
    summary="Preview a bulk operation",
    description=(
        "Computes the exact per-playlist delta a set expression would cause — "
        "union, difference, or intersect of source playlists into a target "
        "(existing or new), dedupe within one playlist, or a subset-to-parent "
        "sync. Nothing is written; the stored preview is what apply performs."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown source or target playlist."},
        422: {"model": ProblemDetail, "description": "The expression is incomplete."},
    },
)
def preview_operation(
    body: PreviewBody,
    session: SessionDep,
    user: CurrentUserDep,
) -> PreviewResource:
    preview = build_preview(
        session,
        user,
        operation=body.operation,
        source_ids=body.source_ids,
        target_id=body.target_id,
        new_playlist_name=body.new_playlist_name,
    )
    return PreviewResource(
        preview_id=preview.id,
        operation=preview.operation,
        manifest=Manifest.model_validate(preview.manifest),
        created_at=preview.created_at,
        links={
            "self": HalLink(href="/v1/ops/preview"),
            "apply": HalLink(href="/v1/ops/apply"),
        },
    )


@router.post(
    "/v1/ops/apply",
    summary="Apply a previewed bulk operation",
    description=(
        "Replays a stored preview exactly as shown — nothing is recomputed. "
        "Refused (409) when any playlist changed since the preview, so what "
        "you saw is always what you get. Journaled as one entry; a partial "
        "result keeps per-playlist outcomes and stays fully undoable."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown preview."},
        409: {
            "model": ProblemDetail,
            "description": "The library changed since the preview — rebuild it.",
        },
    },
)
async def apply_operation(
    body: ApplyBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> ApplyResult:
    preview = session.get(OpPreview, body.preview_id)
    if preview is None or preview.user_id != user.id:
        raise AppError(
            404,
            "Preview not found",
            detail=f"No preview with id {body.preview_id}.",
            error_code="PREVIEW_NOT_FOUND",
        )
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.apply_preview(preview)
    return ApplyResult(
        journal_id=journal.id,
        status=journal.status,
        results=[ApplyEntryResult.model_validate(r) for r in journal.payload["results"]],
        links=_mutation_links(journal),
    )


# ------------------------------------------------------------------ journal


def _journal_resource(journal: MutationJournal) -> JournalEntryResource:
    links: dict[str, HalLink] = {"self": HalLink(href=f"/v1/journal/{journal.id}")}
    if journal.status in (MutationStatus.applied, MutationStatus.partial):
        links["undo"] = HalLink(href=f"/v1/journal/{journal.id}/undo")
    playlist_id = journal.payload.get("playlist_id")
    if playlist_id is not None:
        links["playlist"] = HalLink(href=f"/v1/playlists/{playlist_id}")
    return JournalEntryResource(
        id=journal.id,
        op_type=journal.op_type,
        status=journal.status,
        summary=journal.payload.get("summary", journal.op_type.value),
        created_at=journal.created_at,
        undone_at=journal.undone_at,
        detail=journal.payload,
        links=links,
    )


@router.get(
    "/v1/journal",
    summary="List recorded mutations",
    description=(
        "Every write crate has performed, newest first — the operations log. "
        "Entries with an undo link can be reverted; undone entries stay in "
        "the history."
    ),
)
def list_journal(
    session: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Items to skip from the start.")] = 0,
) -> JournalCollection:
    total = session.exec(
        select(func.count()).select_from(MutationJournal).where(MutationJournal.user_id == user.id)
    ).one()
    rows = session.exec(
        select(MutationJournal)
        .where(MutationJournal.user_id == user.id)
        .order_by(col(MutationJournal.id).desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return JournalCollection(
        items=[_journal_resource(j) for j in rows],
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links("/v1/journal", limit=limit, offset=offset, total=total),
    )


@router.get(
    "/v1/journal/{journal_id}",
    summary="One recorded mutation",
    description="The full journal entry: payload, per-playlist results, status.",
    responses={404: {"model": ProblemDetail, "description": "Unknown journal entry."}},
)
def get_journal_entry(
    journal_id: int, session: SessionDep, user: CurrentUserDep
) -> JournalEntryResource:
    journal = session.get(MutationJournal, journal_id)
    if journal is None or journal.user_id != user.id:
        raise AppError(
            404,
            "Journal entry not found",
            detail=f"No journal entry with id {journal_id}.",
            error_code="JOURNAL_NOT_FOUND",
        )
    return _journal_resource(journal)


@router.post(
    "/v1/journal/{journal_id}/undo",
    summary="Undo a recorded mutation",
    description=(
        "Restores the state the mutation replaced — exact membership and "
        "order for track changes, the previous name/description for renames, "
        "removal of playlists a bulk run created. Works on applied and "
        "partial entries; each entry can be undone once."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown journal entry."},
        409: {
            "model": ProblemDetail,
            "description": "The entry is pending or already undone.",
        },
        502: {
            "model": ProblemDetail,
            "description": "Spotify rejected a write mid-undo; retry to converge.",
        },
    },
)
async def undo_journal_entry(
    journal_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> UndoResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.undo(journal_id)
    return UndoResult(
        journal_id=journal.id,
        status=journal.status,
        links={"journal": HalLink(href=f"/v1/journal/{journal.id}")},
    )
