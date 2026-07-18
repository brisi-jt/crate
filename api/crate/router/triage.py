"""Triage: per-account source setting, queue, per-song intelligence, filing.

The account triages from one source at a time — a designated owned playlist or
Liked Songs (with a ≤N-playlists filter). Each queued song gets per-song filing
intelligence (four separately-labeled evidence signals, current memberships, a
cluster-grounded new-category proposal), files to multiple destinations in one
journaled action, and gets a per-song cleanup step (remove-from-source).

Every write goes through the existing journal/undo system (MutationService).
UMAP/HDBSCAN for the new-category proposal never runs in the request path — the
intelligence endpoint reads the cached cluster proposal or returns it pending
and schedules the background compute (same 202 discipline as the track map).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlmodel import Session, col, select

from crate.deps import (
    CurrentUserDep,
    SessionDep,
    TriageClusterPrecomputerDep,
    WriterFactoryDep,
)
from crate.errors import AppError, ProblemDetail
from crate.model.orm import Playlist, PlaylistTrack, User
from crate.router.playlists import HalLink, _collection_links
from crate.services.analytics.snapshots import (
    EXCLUSION_DEPENDENT_KINDS,
    invalidate_snapshots,
)
from crate.services.mutations.service import MutationService
from crate.services.triage.cluster import read_cluster_proposal
from crate.services.triage.engine import suggest_destinations
from crate.services.triage.evidence import DestinationSuggestion
from crate.services.triage.membership import (
    find_playlists_for_tracks,
    playlist_exclusions,
    playlist_names,
)
from crate.services.triage.queue import QueueSource, load_queue

router = APIRouter(tags=["triage"])

LimitParam = Annotated[int, Query(ge=1, le=100, description="Page size.")]
OffsetParam = Annotated[int, Query(ge=0, description="Items to skip from the start.")]
MaxPlaylistsParam = Annotated[
    int,
    Query(
        ge=0,
        le=50,
        description="Liked-mode filter: only tracks in ≤ this many owned playlists "
        "(0 = orphans). Ignored in playlist mode.",
    ),
]


# ------------------------------------------------------------------ setting


class TriageSettingResource(BaseModel):
    """The account's current triage source."""

    source: Literal["liked", "playlist"]
    playlist_id: int | None = Field(
        description="The source playlist id in playlist mode; null in liked mode."
    )
    playlist_name: str | None = Field(
        default=None, description="The source playlist's name, when set."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class TriageSettingUpdate(BaseModel):
    """Set the triage source. Playlist mode requires a live owned playlist_id."""

    source: Literal["liked", "playlist"]
    playlist_id: int | None = Field(
        default=None, description="Required in playlist mode; ignored in liked mode."
    )

    @model_validator(mode="after")
    def _playlist_needs_id(self) -> "TriageSettingUpdate":
        if self.source == "playlist" and self.playlist_id is None:
            raise ValueError("playlist_id is required when source is 'playlist'")
        return self


def _setting_links() -> dict[str, HalLink]:
    return {
        "self": HalLink(href="/v1/me/triage"),
        "queue": HalLink(href="/v1/triage/queue"),
    }


def _live_owned_playlist(session: Session, user: User, playlist_id: int) -> Playlist | None:
    return session.exec(
        select(Playlist)
        .where(Playlist.id == playlist_id)
        .where(Playlist.user_id == user.id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
        .where(Playlist.is_owned == True)  # noqa: E712 — SQL expression
    ).first()


def _setting_resource(session: Session, user: User) -> TriageSettingResource:
    pid = user.triage_playlist_id
    name = None
    if pid is not None:
        pl = _live_owned_playlist(session, user, pid)
        # A stale id (playlist since deleted) falls back to liked on read.
        if pl is None:
            pid = None
        else:
            name = pl.name
    return TriageSettingResource(
        source="playlist" if pid is not None else "liked",
        playlist_id=pid,
        playlist_name=name,
        links=_setting_links(),
    )


@router.get(
    "/v1/me/triage",
    summary="Current triage source",
    description=(
        "The account's triage source: Liked Songs (default) or a designated owned playlist."
    ),
)
def get_triage_setting(session: SessionDep, user: CurrentUserDep) -> TriageSettingResource:
    return _setting_resource(session, user)


@router.put(
    "/v1/me/triage",
    summary="Set the triage source",
    description=(
        "Switch the triage source. Body is explicit so 'back to Liked Songs' is "
        'always reachable: {"source":"liked"} clears the playlist, '
        '{"source":"playlist","playlist_id":N} designates an owned playlist. '
        "The playlist must be a live owned playlist (422 otherwise)."
    ),
    responses={
        422: {"model": ProblemDetail, "description": "Unknown or unusable triage playlist."}
    },
)
def put_triage_setting(
    update: TriageSettingUpdate, session: SessionDep, user: CurrentUserDep
) -> TriageSettingResource:
    if update.source == "playlist":
        assert update.playlist_id is not None
        if _live_owned_playlist(session, user, update.playlist_id) is None:
            raise AppError(
                422,
                "Invalid triage playlist",
                detail=f"Playlist {update.playlist_id} is not a live owned playlist.",
                error_code="INVALID_TRIAGE_PLAYLIST",
            )
        user.triage_playlist_id = update.playlist_id
    else:
        user.triage_playlist_id = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return _setting_resource(session, user)


# ------------------------------------------------------------------ destinations


class DestinationResource(BaseModel):
    """An owned live playlist the account can file into (or hold out of triage)."""

    id: int
    name: str
    image_url: str | None = Field(
        default=None, description="Spotify playlist cover, when it has one."
    )
    track_count: int = Field(description="Tracks currently in the playlist.")
    triage_excluded: bool = Field(description="True when held out of triage.")


class DestinationCollection(BaseModel):
    items: list[DestinationResource]
    total: int = Field(description="Total owned live playlists.")
    excluded_count: int = Field(description="How many are currently held out of triage.")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class DestinationsUpdate(BaseModel):
    """Bulk-replace the exclusion set: these become excluded, all others eligible."""

    excluded_playlist_ids: list[int] = Field(
        default_factory=list,
        description="The owned live playlists to hold out of triage. Every other "
        "owned live playlist becomes eligible. An empty list clears all exclusions.",
    )


def _owned_live_playlists(session: Session, user: User) -> list[Playlist]:
    return list(
        session.exec(
            select(Playlist)
            .where(Playlist.user_id == user.id)
            .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
            .where(Playlist.is_owned == True)  # noqa: E712 — SQL expression
            .order_by(Playlist.name)
        ).all()
    )


def _destination_collection(session: Session, user: User) -> DestinationCollection:
    rows = _owned_live_playlists(session, user)
    counts: dict[int | None, int] = dict(
        session.exec(
            select(PlaylistTrack.playlist_id, func.count())
            .where(PlaylistTrack.user_id == user.id)
            .group_by(PlaylistTrack.playlist_id)
        ).all()
    )
    items = [
        DestinationResource(
            id=row.id,
            name=row.name,
            image_url=row.image_url,
            track_count=counts.get(row.id, 0),
            triage_excluded=row.triage_excluded,
        )
        for row in rows
        if row.id is not None
    ]
    return DestinationCollection(
        items=items,
        total=len(items),
        excluded_count=sum(1 for i in items if i.triage_excluded),
        links={
            "self": HalLink(href="/v1/triage/destinations"),
            "queue": HalLink(href="/v1/triage/queue"),
        },
    )


@router.get(
    "/v1/triage/destinations",
    summary="List filing destinations",
    description=(
        "The account's owned live playlists — the pool of filing destinations — "
        "each flagged with whether it's held out of triage. Spotify's API can't "
        "see playlist folders, so this is where destinations are scoped."
    ),
)
def list_destinations(session: SessionDep, user: CurrentUserDep) -> DestinationCollection:
    return _destination_collection(session, user)


@router.put(
    "/v1/triage/destinations",
    summary="Set which playlists are held out of triage",
    description=(
        "Bulk-replace the exclusion set. The given playlists become held out of "
        "triage — dropped from suggestion scoring, from the liked-mode ≤N "
        "membership count, and from the new-category population — and every other "
        "owned live playlist becomes eligible. Idempotent; an empty list clears "
        "all exclusions. Every id must be an owned live playlist (422 otherwise)."
    ),
    responses={422: {"model": ProblemDetail, "description": "An id isn't an owned live playlist."}},
)
def put_destinations(
    update: DestinationsUpdate, session: SessionDep, user: CurrentUserDep
) -> DestinationCollection:
    owned = _owned_live_playlists(session, user)
    owned_ids = {p.id for p in owned}
    requested = set(update.excluded_playlist_ids)
    unknown = requested - owned_ids
    if unknown:
        raise AppError(
            422,
            "Invalid triage playlist",
            detail=f"Not owned live playlists: {sorted(unknown)}.",
            error_code="INVALID_TRIAGE_PLAYLIST",
        )
    # Bulk replace: only touch rows whose flag actually changes, and invalidate
    # the caches whose output depends on the exclusion set when it did change.
    changed = False
    for playlist in owned:
        target = playlist.id in requested
        if playlist.triage_excluded != target:
            playlist.triage_excluded = target
            session.add(playlist)
            changed = True
    if changed:
        assert user.id is not None
        invalidate_snapshots(session, user.id, kinds=EXCLUSION_DEPENDENT_KINDS)
    session.commit()
    return _destination_collection(session, user)


# ------------------------------------------------------------------ source


def _current_source(session: Session, user: User, max_playlists: int) -> QueueSource:
    """Resolve the account's active source into a QueueSource.

    A stale triage_playlist_id (playlist deleted) falls back to Liked Songs.
    """
    pid = user.triage_playlist_id
    if pid is not None and _live_owned_playlist(session, user, pid) is not None:
        return QueueSource(playlist_id=pid)
    return QueueSource(liked=True, max_playlists=max_playlists)


# ------------------------------------------------------------------ queue


class QueueTrackResource(BaseModel):
    track_id: int
    spotify_id: str
    name: str
    artist: str = Field(description="Primary artist name; empty when the track has no artists.")
    album_image_url: str | None = Field(
        default=None, description="Small album-art thumb; null until the album is imaged."
    )


class QueueCollection(BaseModel):
    items: list[QueueTrackResource]
    total: int = Field(description="Total tracks in the filtered queue, ignoring pagination.")
    limit: int
    offset: int
    source: Literal["liked", "playlist"]
    max_playlists: int = Field(description="The ≤N filter in effect (liked mode only).")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.get(
    "/v1/triage/queue",
    summary="The triage queue",
    description=(
        "Tracks awaiting a filing decision, oldest-waiting first. In playlist "
        "mode: the source playlist's tracks by added_at ascending. In Liked "
        "mode: saved tracks in ≤ max_playlists owned playlists (default 0 = "
        "orphans)."
    ),
)
def get_triage_queue(
    session: SessionDep,
    user: CurrentUserDep,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
    max_playlists: MaxPlaylistsParam = 0,
) -> QueueCollection:
    assert user.id is not None
    source = _current_source(session, user, max_playlists)
    result = load_queue(session, user.id, source, limit=limit, offset=offset)
    return QueueCollection(
        items=[
            QueueTrackResource(
                track_id=e.track_id,
                spotify_id=e.spotify_id,
                name=e.name,
                artist=e.artist,
                album_image_url=e.album_image_url,
            )
            for e in result.items
        ],
        total=result.total,
        limit=limit,
        offset=offset,
        source="playlist" if source.playlist_id is not None else "liked",
        max_playlists=source.max_playlists,
        links=_collection_links("/v1/triage/queue", limit=limit, offset=offset, total=result.total),
    )


# ------------------------------------------------------------------ intelligence


class MembershipResource(BaseModel):
    count: int
    playlist_ids: list[int]
    playlist_names: list[str]
    excluded: list[bool] = Field(
        default_factory=list,
        description="Per membership: whether that playlist is held out of triage.",
    )


class ClusterProposalResource(BaseModel):
    suggested_name: str
    founding_track_ids: list[int]
    size: int


class NewCategoryResource(BaseModel):
    status: Literal["ready", "pending", "empty"]
    proposals: list[ClusterProposalResource]


class IntelligenceResource(BaseModel):
    """Per-song filing intelligence: three panels."""

    track_id: int
    suggestions: list[DestinationSuggestion]
    memberships: MembershipResource
    new_category: NewCategoryResource
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.get(
    "/v1/triage/tracks/{track_id}/intelligence",
    summary="Per-song filing intelligence",
    description=(
        "Three panels for one queued track: ranked destination suggestions "
        "(each with four separately-labeled evidence signals — never a blended "
        "score), current owned-playlist memberships, and a cluster-grounded "
        "new-category proposal. The proposal's clustering is precomputed in the "
        "background; a cold read returns new_category.status='pending'."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown track."}},
)
def get_intelligence(
    track_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    background: BackgroundTasks,
    precompute: TriageClusterPrecomputerDep,
    max_playlists: MaxPlaylistsParam = 0,
) -> IntelligenceResource:
    assert user.id is not None
    from crate.model.orm import Track

    if session.get(Track, track_id) is None:
        raise AppError(
            404,
            "Track not found",
            detail=f"No track with id {track_id}.",
            error_code="TRACK_NOT_FOUND",
        )

    suggestions = suggest_destinations(session, user, track_id)

    membership_map = find_playlists_for_tracks(session, user.id, [track_id])
    member_ids = membership_map.get(track_id, [])
    names = playlist_names(session, user.id)
    exclusions = playlist_exclusions(session, user.id)
    memberships = MembershipResource(
        count=len(member_ids),
        playlist_ids=member_ids,
        playlist_names=[names.get(pid, "") for pid in member_ids],
        excluded=[exclusions.get(pid, False) for pid in member_ids],
    )

    source = _current_source(session, user, max_playlists)
    cluster = read_cluster_proposal(session, user, source)
    if cluster.status == "pending":
        background.add_task(precompute, user.id, source)
    new_category = NewCategoryResource(
        status=cluster.status,  # type: ignore[arg-type]
        proposals=[
            ClusterProposalResource(
                suggested_name=p.suggested_name,
                founding_track_ids=p.founding_track_ids,
                size=p.size,
            )
            for p in cluster.proposals
        ],
    )

    return IntelligenceResource(
        track_id=track_id,
        suggestions=suggestions,
        memberships=memberships,
        new_category=new_category,
        links={
            "self": HalLink(href=f"/v1/triage/tracks/{track_id}/intelligence"),
            "apply": HalLink(href="/v1/triage/apply"),
        },
    )


# ------------------------------------------------------------------ apply


class NewPlaylistBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    seed_track_ids: list[int] = Field(
        default_factory=list,
        description="Cluster members to seed the new playlist with; the filed "
        "track is always included.",
    )


class ApplyBody(BaseModel):
    track_id: int
    destination_playlist_ids: list[int] = Field(
        default_factory=list, description="Existing owned playlists to file the track into."
    )
    new_playlist: NewPlaylistBody | None = Field(
        default=None, description="Create and seed a new playlist as an additional destination."
    )
    unsave: bool = Field(
        default=False, description="Also remove the track from Liked Songs (liked-mode filing)."
    )

    @model_validator(mode="after")
    def _at_least_one_destination(self) -> "ApplyBody":
        if not self.destination_playlist_ids and self.new_playlist is None:
            raise ValueError("provide at least one destination playlist or a new_playlist")
        return self


class ApplyResult(BaseModel):
    journal_id: int
    status: str
    links: dict[str, HalLink] = Field(serialization_alias="_links")


TRIAGE_WRITE_ERRORS: dict[int | str, dict] = {
    404: {"model": ProblemDetail, "description": "Unknown playlist or track."},
    409: {"model": ProblemDetail, "description": "Spotify isn't connected, or membership changed."},
    502: {
        "model": ProblemDetail,
        "description": "Spotify rejected the write; the journal records the previous state.",
    },
}


@router.post(
    "/v1/triage/apply",
    summary="File a track (one journaled action)",
    description=(
        "Files one track to multiple destinations in a single journaled action: "
        "adds it to the destination playlists, optionally creates and seeds a "
        "new playlist, and optionally unsaves it from Liked Songs. Undo the "
        "whole filing with one call via the returned journal link."
    ),
    responses=TRIAGE_WRITE_ERRORS,
)
async def apply_filing(
    body: ApplyBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> ApplyResult:
    new_playlist = (
        {"name": body.new_playlist.name, "seed_track_ids": body.new_playlist.seed_track_ids}
        if body.new_playlist is not None
        else None
    )
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        journal = await service.file_track(
            track_id=body.track_id,
            destination_playlist_ids=body.destination_playlist_ids,
            new_playlist=new_playlist,
            unsave=body.unsave,
        )
    return ApplyResult(
        journal_id=journal.id,
        status=journal.status.value,
        links={
            "journal": HalLink(href=f"/v1/journal/{journal.id}"),
            "undo": HalLink(href=f"/v1/journal/{journal.id}/undo"),
        },
    )


# ------------------------------------------------------------------ cleanup


class CleanupBody(BaseModel):
    source: Literal["liked", "playlist"]
    playlist_id: int | None = Field(
        default=None, description="Required for playlist-source cleanup."
    )
    track_ids: list[int] = Field(
        min_length=1,
        description="The tracks to remove from the source (from the popup checkboxes).",
    )

    @model_validator(mode="after")
    def _playlist_needs_id(self) -> "CleanupBody":
        if self.source == "playlist" and self.playlist_id is None:
            raise ValueError("playlist_id is required when source is 'playlist'")
        return self


class CleanupResult(BaseModel):
    journal_id: int
    status: str
    removed: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.post(
    "/v1/triage/cleanup",
    summary="Remove filed tracks from the source",
    description=(
        "The post-apply cleanup step: remove the confirmed tracks from the "
        "triage source — from the source playlist (playlist mode) or from Liked "
        "Songs (liked mode). Journaled and undoable."
    ),
    responses=TRIAGE_WRITE_ERRORS,
)
async def cleanup_source(
    body: CleanupBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> CleanupResult:
    async with writer_factory(session, user) as writer:
        service = MutationService(session=session, writer=writer, user=user)
        if body.source == "liked":
            journal = await service.unsave_tracks(body.track_ids)
            removed = len(body.track_ids)
        else:
            assert body.playlist_id is not None
            positions = _positions_for(session, user, body.playlist_id, body.track_ids)
            if not positions:
                raise AppError(
                    404,
                    "No matching tracks",
                    detail="None of the given tracks are in that playlist.",
                    error_code="MEMBERSHIP_STALE",
                )
            journal = await service.remove_tracks(body.playlist_id, positions)
            removed = len(positions)
    return CleanupResult(
        journal_id=journal.id,
        status=journal.status.value,
        removed=removed,
        links={
            "journal": HalLink(href=f"/v1/journal/{journal.id}"),
            "undo": HalLink(href=f"/v1/journal/{journal.id}/undo"),
        },
    )


def _positions_for(
    session: Session, user: User, playlist_id: int, track_ids: list[int]
) -> list[int]:
    """0-based positions of the given track ids within the playlist (all occurrences)."""
    rows = session.exec(
        select(PlaylistTrack)
        .where(PlaylistTrack.user_id == user.id)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .where(col(PlaylistTrack.track_id).in_(track_ids))
        .order_by(PlaylistTrack.position)
    ).all()
    return [row.position for row in rows]
