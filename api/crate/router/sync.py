"""Sync trigger and status."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from crate.deps import CurrentUserDep, SessionDep, SyncRunner, get_sync_runner
from crate.errors import ProblemDetail
from crate.model.enums import CredentialStatus
from crate.model.orm import Playlist, SpotifyCredential, SyncEvent

router = APIRouter(prefix="/v1/sync", tags=["sync"])

SyncRunnerDep = Annotated[SyncRunner, Depends(get_sync_runner)]


class HalLink(BaseModel):
    href: str


class SyncResult(BaseModel):
    """Outcome of a completed sync pass."""

    playlists_created: int = Field(description="Playlists seen for the first time.")
    playlists_synced: int = Field(description="Playlists whose membership was refreshed.")
    playlists_renamed: int = Field(description="Playlists whose name changed.")
    playlists_deleted: int = Field(description="Playlists no longer present on Spotify.")
    playlists_skipped: int = Field(
        description="Playlists skipped because their snapshot was unchanged."
    )
    tracks_added: int = Field(description="Track additions detected across all playlists.")
    tracks_removed: int = Field(description="Track removals detected across all playlists.")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class SyncStatus(BaseModel):
    """Current sync health for the account."""

    spotify_connected: bool = Field(description="Whether a Spotify credential is stored.")
    needs_reauth: bool = Field(
        description="True when Spotify rejected the stored credential; reconnect to resume."
    )
    playlist_count: int = Field(description="Playlists currently tracked (deleted ones excluded).")
    last_synced_at: datetime | None = Field(
        description="Completion time of the most recent sync of any playlist."
    )
    last_event_at: datetime | None = Field(description="Time of the most recent change event.")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


@router.post(
    "",
    summary="Run a sync now",
    description=(
        "Fetches the library from Spotify and reconciles it into crate: new "
        "playlists are recorded, changed playlists are diffed into add/remove/"
        "reorder events, unchanged playlists are skipped via snapshot comparison. "
        "Runs synchronously and returns the pass's counts."
    ),
    responses={
        409: {
            "model": ProblemDetail,
            "description": "No Spotify credential, or the credential needs re-authorization.",
        }
    },
)
async def trigger_sync(
    session: SessionDep, user: CurrentUserDep, runner: SyncRunnerDep
) -> SyncResult:
    report = await runner(session, user)
    return SyncResult(
        playlists_created=report.playlists_created,
        playlists_synced=report.playlists_synced,
        playlists_renamed=report.playlists_renamed,
        playlists_deleted=report.playlists_deleted,
        playlists_skipped=report.playlists_skipped,
        tracks_added=report.tracks_added,
        tracks_removed=report.tracks_removed,
        links={
            "status": HalLink(href="/v1/sync/status"),
            "playlists": HalLink(href="/v1/playlists"),
        },
    )


@router.get(
    "/status",
    summary="Sync health",
    description=(
        "Connection state, playlist count, and freshness timestamps. When "
        "needs_reauth is true, follow the connect link to restore access."
    ),
)
def sync_status(session: SessionDep, user: CurrentUserDep) -> SyncStatus:
    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).first()
    playlist_count = session.exec(
        select(func.count())
        .select_from(Playlist)
        .where(Playlist.user_id == user.id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).one()
    last_synced_at = session.exec(
        select(func.max(Playlist.last_synced_at)).where(Playlist.user_id == user.id)
    ).one()
    last_event_at = session.exec(
        select(func.max(SyncEvent.observed_at)).where(SyncEvent.user_id == user.id)
    ).one()

    needs_reauth = credential is not None and credential.status == CredentialStatus.needs_reauth
    links = {
        "self": HalLink(href="/v1/sync/status"),
        "sync": HalLink(href="/v1/sync"),
        "playlists": HalLink(href="/v1/playlists"),
    }
    if credential is None or needs_reauth:
        links["connect"] = HalLink(href="/v1/auth/spotify/connect")

    return SyncStatus(
        spotify_connected=credential is not None,
        needs_reauth=needs_reauth,
        playlist_count=playlist_count,
        last_synced_at=last_synced_at,
        last_event_at=last_event_at,
        links=links,
    )
