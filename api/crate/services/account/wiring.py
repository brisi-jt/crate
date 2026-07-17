"""Production wiring for account-data sync passes.

Builds an authenticated SpotifyClient per pass via the shared credential
funnel (409 problems when disconnected or needing re-auth, needs_reauth
status flips, rotated-token persistence) and runs the requested streams.
"""

import logging
from dataclasses import dataclass, field

from sqlmodel import Session

from crate.model.orm import User
from crate.services.account.plays import RecentPlaysReport, capture_recent_plays
from crate.services.account.saved import SavedTracksReport, sync_saved_tracks
from crate.services.account.top import TopItemsReport, capture_top_items
from crate.services.analytics.engine import recompute_all
from crate.services.mutations.wiring import spotify_client_for_user
from crate.services.sync import run_sync_for_user

logger = logging.getLogger(__name__)


@dataclass
class AccountSyncReport:
    """Combined counts from one on-demand account sync."""

    saved: SavedTracksReport = field(default_factory=SavedTracksReport)
    plays: RecentPlaysReport = field(default_factory=RecentPlaysReport)
    top: TopItemsReport = field(default_factory=TopItemsReport)


async def run_account_sync_for_user(session: Session, user: User) -> AccountSyncReport:
    """All three account streams in one pass with one client.

    The re-auth restore path calls this right after a reconnect to bring
    saved tracks, play history and top-items snapshots back in step.
    """
    async with spotify_client_for_user(session, user) as client:
        saved = await sync_saved_tracks(session, client, user)
        plays = await capture_recent_plays(session, client, user)
        top = await capture_top_items(session, client, user)
    return AccountSyncReport(saved=saved, plays=plays, top=top)


async def run_recent_plays_for_user(session: Session, user: User) -> RecentPlaysReport:
    """Scheduler job: one recently-played capture."""
    async with spotify_client_for_user(session, user) as client:
        return await capture_recent_plays(session, client, user)


async def run_nightly_for_user(session: Session, user: User) -> None:
    """Scheduler job: saved-tracks diff, full playlist sync, then a cache warm.

    The post-sync recompute rebuilds every analytics payload — most importantly
    the track map, whose UMAP+HDBSCAN never runs in the request path — so the
    first read after a nightly sync is warm instead of a 202. A recompute
    failure is best-effort: it must never fail the sync itself.
    """
    async with spotify_client_for_user(session, user) as client:
        await sync_saved_tracks(session, client, user)
    await run_sync_for_user(session, user)
    try:
        recompute_all(session, user)
    except Exception:
        # Cache warm is best-effort — never fail the nightly sync over it.
        logger.exception("post-sync analytics recompute failed for user %s", user.id)


async def run_top_items_for_user(session: Session, user: User) -> TopItemsReport:
    """Scheduler job: one top-items snapshot set."""
    async with spotify_client_for_user(session, user) as client:
        return await capture_top_items(session, client, user)


__all__ = [
    "AccountSyncReport",
    "run_account_sync_for_user",
    "run_nightly_for_user",
    "run_recent_plays_for_user",
    "run_top_items_for_user",
]
