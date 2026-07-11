"""Account data: saved-tracks library, listening history, top-items rankings."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from crate.deps import AccountSyncRunner, CurrentUserDep, SessionDep, get_account_sync_runner
from crate.errors import ProblemDetail
from crate.model.enums import TopItemKind, TopTimeRange
from crate.model.orm import PlayEvent, SavedTrack, TopItemsSnapshot, Track
from crate.router.playlists import HalLink, TrackResource, _collection_links

router = APIRouter(tags=["account"])

LimitParam = Annotated[int, Query(ge=1, le=100, description="Page size.")]
OffsetParam = Annotated[int, Query(ge=0, description="Items to skip from the start.")]

AccountSyncRunnerDep = Annotated[AccountSyncRunner, Depends(get_account_sync_runner)]


def _track_resource(track: Track) -> TrackResource:
    return TrackResource(
        id=track.id,
        spotify_id=track.spotify_id,
        isrc=track.isrc,
        name=track.name,
        artists=track.artists,
        album_name=track.album_name,
        duration_ms=track.duration_ms,
    )


class SavedTrackResource(BaseModel):
    """One track in the saved-tracks (Liked Songs) library."""

    saved_at: datetime | None = Field(description="When the track was saved on Spotify.")
    is_removed: bool = Field(
        description="True when the track has since been removed from the library."
    )
    removed_at: datetime | None = Field(
        description="When the removal was observed, for removed tracks."
    )
    track: TrackResource


class SavedTrackCollection(BaseModel):
    items: list[SavedTrackResource]
    total: int = Field(description="Total saved tracks matching the query, ignoring pagination.")
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class PlayEventResource(BaseModel):
    """One play from the listening history."""

    played_at: datetime = Field(description="When the play finished, per Spotify.")
    context_type: str | None = Field(
        description="Where it played, when known: playlist, album, artist or show."
    )
    context_uri: str | None = Field(description="Spotify URI of that context.")
    track: TrackResource


class PlayEventCollection(BaseModel):
    items: list[PlayEventResource]
    total: int = Field(description="Total recorded plays, ignoring pagination.")
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class TopItemsResource(BaseModel):
    """The latest ranking for one kind x time-range combination."""

    kind: TopItemKind
    time_range: TopTimeRange
    captured_at: datetime = Field(description="When this ranking was captured.")
    items: list[dict[str, Any]] = Field(
        description="Ranked list, best first: {rank, spotify_id, name} plus "
        "artist names for track rankings."
    )


class TopItemsCollection(BaseModel):
    items: list[TopItemsResource]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class AccountSyncResult(BaseModel):
    """Outcome of an on-demand account-data sync."""

    saved_added: int = Field(description="Tracks newly saved (or re-saved) since the last pass.")
    saved_removed: int = Field(description="Tracks removed from the library since the last pass.")
    saved_total: int = Field(description="Saved tracks currently in the library.")
    plays_captured: int = Field(description="New plays recorded from the recent-plays window.")
    top_snapshots: int = Field(description="Top-items rankings captured (artist/track x 3 ranges).")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.get(
    "/v1/library/saved",
    summary="List saved tracks",
    description=(
        "The account's saved-tracks (Liked Songs) library as of the last "
        "sync, newest saves first. Removed tracks stay on record — include "
        "them with include_removed to see the library's history."
    ),
)
def list_saved_tracks(
    session: SessionDep,
    user: CurrentUserDep,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
    include_removed: Annotated[
        bool, Query(description="Include tracks that have since been removed from the library.")
    ] = False,
) -> SavedTrackCollection:
    filters = [SavedTrack.user_id == user.id]
    if not include_removed:
        filters.append(SavedTrack.is_removed == False)  # noqa: E712 — SQL expression

    total = session.exec(select(func.count()).select_from(SavedTrack).where(*filters)).one()
    rows = session.exec(
        select(SavedTrack, Track)
        .where(*filters)
        .where(SavedTrack.track_id == Track.id)
        .order_by(col(SavedTrack.saved_at).desc(), col(SavedTrack.id).desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        SavedTrackResource(
            saved_at=saved.saved_at,
            is_removed=saved.is_removed,
            removed_at=saved.removed_at,
            track=_track_resource(track),
        )
        for saved, track in rows
    ]
    return SavedTrackCollection(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links("/v1/library/saved", limit=limit, offset=offset, total=total),
    )


@router.get(
    "/v1/listening/recent",
    summary="List recent plays",
    description=(
        "Play history accumulated from Spotify's recently-played feed, "
        "newest first. Each play carries its context (which playlist, album "
        "or artist it played from) when Spotify reports one."
    ),
)
def list_recent_plays(
    session: SessionDep,
    user: CurrentUserDep,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> PlayEventCollection:
    total = session.exec(
        select(func.count()).select_from(PlayEvent).where(PlayEvent.user_id == user.id)
    ).one()
    rows = session.exec(
        select(PlayEvent, Track)
        .where(PlayEvent.user_id == user.id)
        .where(PlayEvent.track_id == Track.id)
        .order_by(col(PlayEvent.played_at).desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        PlayEventResource(
            played_at=event.played_at,
            context_type=event.context_type,
            context_uri=event.context_uri,
            track=_track_resource(track),
        )
        for event, track in rows
    ]
    return PlayEventCollection(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links("/v1/listening/recent", limit=limit, offset=offset, total=total),
    )


@router.get(
    "/v1/listening/top",
    summary="Current top artists and tracks",
    description=(
        "The latest captured ranking for each combination of kind (artist, "
        "track) and time range (short ≈ 4 weeks, medium ≈ 6 months, long ≈ "
        "1 year). Combos never captured are omitted."
    ),
)
def list_top_items(
    session: SessionDep,
    user: CurrentUserDep,
    kind: Annotated[
        TopItemKind | None, Query(description="Only artist or only track rankings.")
    ] = None,
    time_range: Annotated[
        TopTimeRange | None, Query(description="Only one affinity window.")
    ] = None,
) -> TopItemsCollection:
    kinds = [kind] if kind is not None else list(TopItemKind)
    ranges = [time_range] if time_range is not None else list(TopTimeRange)

    items: list[TopItemsResource] = []
    for item_kind in kinds:
        for item_range in ranges:
            row = session.exec(
                select(TopItemsSnapshot)
                .where(TopItemsSnapshot.user_id == user.id)
                .where(TopItemsSnapshot.kind == item_kind)
                .where(TopItemsSnapshot.time_range == item_range)
                .order_by(col(TopItemsSnapshot.captured_at).desc())
                .limit(1)
            ).first()
            if row is not None:
                items.append(
                    TopItemsResource(
                        kind=row.kind,
                        time_range=row.time_range,
                        captured_at=row.captured_at,
                        items=row.items,
                    )
                )

    return TopItemsCollection(
        items=items,
        links={"self": HalLink(href="/v1/listening/top")},
    )


@router.post(
    "/v1/account/sync",
    summary="Sync account data now",
    description=(
        "Refreshes all three account-data streams in one pass: the "
        "saved-tracks library is re-walked and diffed, the recent-plays "
        "window is captured, and a fresh set of top-items rankings is "
        "snapshotted. Playlist sync is separate — POST /v1/sync."
    ),
    responses={
        409: {
            "model": ProblemDetail,
            "description": "No Spotify credential, or the credential needs re-authorization.",
        }
    },
)
async def trigger_account_sync(
    session: SessionDep, user: CurrentUserDep, runner: AccountSyncRunnerDep
) -> AccountSyncResult:
    report = await runner(session, user)
    return AccountSyncResult(
        saved_added=report.saved.added,
        saved_removed=report.saved.removed,
        saved_total=report.saved.total_saved,
        plays_captured=report.plays.captured,
        top_snapshots=report.top.snapshots,
        links={
            "status": HalLink(href="/v1/sync/status"),
            "saved": HalLink(href="/v1/library/saved"),
            "recent": HalLink(href="/v1/listening/recent"),
            "top": HalLink(href="/v1/listening/top"),
        },
    )
