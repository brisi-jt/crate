"""Read access to synced playlists and their tracks."""

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from crate.deps import CurrentUserDep, SessionDep
from crate.errors import AppError, ProblemDetail
from crate.model.enums import PlaylistSyncStatus
from crate.model.orm import Playlist, PlaylistTrack, Track

router = APIRouter(prefix="/v1/playlists", tags=["playlists"])

LimitParam = Annotated[int, Query(ge=1, le=100, description="Page size.")]
OffsetParam = Annotated[int, Query(ge=0, description="Items to skip from the start.")]


class HalLink(BaseModel):
    href: str


class PlaylistResource(BaseModel):
    """A synced playlist."""

    id: int = Field(description="crate's playlist id — use it in playlist URLs.")
    spotify_id: str = Field(description="Spotify's playlist id.")
    name: str
    description: str | None
    snapshot_id: str | None = Field(description="Spotify snapshot at the last sync.")
    is_owned: bool = Field(description="True when the account owns the playlist (vs follows it).")
    is_deleted: bool = Field(description="True when the playlist is gone from Spotify.")
    status: PlaylistSyncStatus
    track_count: int = Field(description="Tracks currently in the playlist.")
    last_synced_at: datetime | None
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class PlaylistCollection(BaseModel):
    items: list[PlaylistResource]
    total: int = Field(description="Total playlists matching the query, ignoring pagination.")
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class TrackResource(BaseModel):
    """A track in the global catalog."""

    id: int = Field(description="crate's track id.")
    spotify_id: str
    isrc: str | None = Field(description="International Standard Recording Code, when known.")
    name: str
    artists: list[dict[str, Any]] = Field(
        description="Ordered artists as {spotify_id, name} objects."
    )
    album_name: str | None
    duration_ms: int | None


class PlaylistTrackResource(BaseModel):
    """One playlist entry: a track at a position."""

    position: int = Field(description="0-based position within the playlist.")
    added_at: datetime | None = Field(description="When the track was added on Spotify.")
    track: TrackResource


class PlaylistTrackCollection(BaseModel):
    items: list[PlaylistTrackResource]
    total: int = Field(description="Total tracks in the playlist, ignoring pagination.")
    limit: int
    offset: int
    links: dict[str, HalLink] = Field(serialization_alias="_links")


def _collection_links(
    base_path: str, *, limit: int, offset: int, total: int, extra: dict[str, str] | None = None
) -> dict[str, HalLink]:
    def page_href(page_offset: int) -> str:
        return f"{base_path}?{urlencode({'limit': limit, 'offset': page_offset})}"

    links = {"self": HalLink(href=page_href(offset))}
    if offset + limit < total:
        links["next"] = HalLink(href=page_href(offset + limit))
    if offset > 0:
        links["prev"] = HalLink(href=page_href(max(offset - limit, 0)))
    for name, href in (extra or {}).items():
        links[name] = HalLink(href=href)
    return links


@router.get(
    "",
    summary="List playlists",
    description=(
        "Synced playlists for the account, ordered by name. Deleted playlists "
        "are excluded unless include_deleted is set."
    ),
)
def list_playlists(
    session: SessionDep,
    user: CurrentUserDep,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
    include_deleted: Annotated[
        bool, Query(description="Include playlists that no longer exist on Spotify.")
    ] = False,
) -> PlaylistCollection:
    filters = [Playlist.user_id == user.id]
    if not include_deleted:
        filters.append(Playlist.is_deleted == False)  # noqa: E712 — SQL expression

    total = session.exec(select(func.count()).select_from(Playlist).where(*filters)).one()
    rows = session.exec(
        select(Playlist).where(*filters).order_by(Playlist.name).limit(limit).offset(offset)
    ).all()

    counts: dict[int | None, int] = dict(
        session.exec(
            select(PlaylistTrack.playlist_id, func.count())
            .where(PlaylistTrack.user_id == user.id)
            .group_by(PlaylistTrack.playlist_id)
        ).all()
    )

    items = [
        PlaylistResource(
            id=row.id,
            spotify_id=row.spotify_id,
            name=row.name,
            description=row.description,
            snapshot_id=row.snapshot_id,
            is_owned=row.is_owned,
            is_deleted=row.is_deleted,
            status=row.status,
            track_count=counts.get(row.id, 0),
            last_synced_at=row.last_synced_at,
            links={
                "self": HalLink(href=f"/v1/playlists/{row.id}"),
                "tracks": HalLink(href=f"/v1/playlists/{row.id}/tracks"),
            },
        )
        for row in rows
    ]
    return PlaylistCollection(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links("/v1/playlists", limit=limit, offset=offset, total=total),
    )


@router.get(
    "/{playlist_id}/tracks",
    summary="List a playlist's tracks",
    description=(
        "Tracks in playlist order. Playlists can hold thousands of tracks — "
        "page through with limit/offset and follow the next link."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown playlist."}},
)
def list_playlist_tracks(
    playlist_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    limit: LimitParam = 100,
    offset: OffsetParam = 0,
) -> PlaylistTrackCollection:
    playlist = session.exec(
        select(Playlist).where(Playlist.id == playlist_id).where(Playlist.user_id == user.id)
    ).first()
    if playlist is None:
        raise AppError(
            404,
            "Playlist not found",
            detail=f"No playlist with id {playlist_id}.",
            error_code="PLAYLIST_NOT_FOUND",
        )

    total = session.exec(
        select(func.count())
        .select_from(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
    ).one()
    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(PlaylistTrack.position)
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        PlaylistTrackResource(
            position=pt.position,
            added_at=pt.added_at,
            track=TrackResource(
                id=track.id,
                spotify_id=track.spotify_id,
                isrc=track.isrc,
                name=track.name,
                artists=track.artists,
                album_name=track.album_name,
                duration_ms=track.duration_ms,
            ),
        )
        for pt, track in rows
    ]
    return PlaylistTrackCollection(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        links=_collection_links(
            f"/v1/playlists/{playlist_id}/tracks",
            limit=limit,
            offset=offset,
            total=total,
            extra={"playlist": f"/v1/playlists/{playlist_id}"},
        ),
    )
