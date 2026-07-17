"""Shared FastAPI dependencies."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Protocol

from fastapi import Depends
from sqlmodel import Session, select

from crate.db import get_engine, get_session
from crate.errors import AppError
from crate.model.orm import RadioSession, User
from crate.services.account.wiring import AccountSyncReport, run_account_sync_for_user
from crate.services.analytics import engine as analytics_engine
from crate.services.discovery.wiring import DiscoveryReport, run_discovery
from crate.services.enrichment.orchestrator import EnrichmentReport, Stage, run_enrichment
from crate.services.mutations.wiring import spotify_writer_for_user
from crate.services.mutations.writer import SpotifyWriter
from crate.services.previews.refresh import RefreshedPreview
from crate.services.previews.wiring import refresh_preview_for_user
from crate.services.radio.wiring import build_radio_for_user
from crate.services.spotify.auth import SpotifyAuthGateway
from crate.services.sync import SyncReport, run_sync_for_user
from crate.services.triage.queue import QueueSource
from crate.settings import get_settings

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(session: SessionDep) -> User:
    """Resolve the requesting user.

    Currently a development bypass: CRATE_DEV_USER names the user (created on
    first request). Clerk JWT verification will replace this body without
    changing the dependency's signature, so routes stay untouched.
    """
    settings = get_settings()
    if not settings.dev_user:
        raise AppError(
            401,
            "Not authenticated",
            detail="No authenticated user. Set CRATE_DEV_USER for local development.",
            error_code="AUTH_REQUIRED",
        )
    user = session.exec(select(User).where(User.clerk_user_id == settings.dev_user)).first()
    if user is None:
        user = User(clerk_user_id=settings.dev_user)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]

SyncRunner = Callable[[Session, User], Awaitable[SyncReport]]


def get_sync_runner() -> SyncRunner:
    return run_sync_for_user


AccountSyncRunner = Callable[[Session, User], Awaitable[AccountSyncReport]]


def get_account_sync_runner() -> AccountSyncRunner:
    return run_account_sync_for_user


# (session, batch_size, *, time_budget_seconds, stage) -> report. Tests
# override with a fake honouring the same keyword-only signature.
class EnrichmentRunner(Protocol):
    async def __call__(
        self,
        session: Session,
        batch_size: int,
        *,
        time_budget_seconds: float = ...,
        stage: Stage = ...,
    ) -> EnrichmentReport: ...


def get_enrichment_runner() -> EnrichmentRunner:
    return run_enrichment


# (session, user, playlist_id, limit, genre_seed) -> report. Tests override
# with a fake.
DiscoveryRunner = Callable[[Session, User, int | None, int, str | None], Awaitable[DiscoveryReport]]


async def _discovery_runner(
    session: Session,
    user: User,
    playlist_id: int | None,
    limit: int,
    genre_seed: str | None,
) -> DiscoveryReport:
    return await run_discovery(
        session, user, playlist_id=playlist_id, limit=limit, genre_seed=genre_seed
    )


def get_discovery_runner() -> DiscoveryRunner:
    return _discovery_runner


# (session, user, playlist_id, track_ids, genre_name, length, discovery_ratio)
# -> persisted radio session. Tests override with an offline builder.
RadioBuilder = Callable[
    [Session, User, int | None, list[int] | None, str | None, int, float],
    Awaitable[RadioSession],
]


def get_radio_builder() -> RadioBuilder:
    return build_radio_for_user


# Async context manager yielding a write-capable Spotify surface for a user.
# Routes acquire it per-request; tests override with an in-memory fake.
WriterFactory = Callable[[Session, User], AbstractAsyncContextManager[SpotifyWriter]]


def get_writer_factory() -> WriterFactory:
    return spotify_writer_for_user


WriterFactoryDep = Annotated[WriterFactory, Depends(get_writer_factory)]


# (session, user, *, track_id, candidate_id, radio_item_id) -> refreshed
# preview. Tests override with an offline fake.
class PreviewRefresher(Protocol):
    async def __call__(
        self,
        session: Session,
        user: User,
        *,
        track_id: int | None = ...,
        candidate_id: int | None = ...,
        radio_item_id: int | None = ...,
    ) -> RefreshedPreview: ...


def get_preview_refresher() -> PreviewRefresher:
    return refresh_preview_for_user


# (user_id, owned_only) -> None. Runs the heavy track-map compute OUTSIDE the
# request path — a FastAPI BackgroundTask after a 202. Opens its own session
# because the request session is closed by the time the task runs. Tests
# override with a synchronous recorder.
MapPrecomputer = Callable[[int, bool], Awaitable[None]]


async def _precompute_track_map(user_id: int, owned_only: bool) -> None:
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None:  # pragma: no cover - defensive
            return
        analytics_engine.precompute_track_map(session, user, owned_only=owned_only)


def get_map_precomputer() -> MapPrecomputer:
    return _precompute_track_map


MapPrecomputerDep = Annotated[MapPrecomputer, Depends(get_map_precomputer)]


# (user_id, source) -> None. Runs the triage queue-cluster UMAP/HDBSCAN OUTSIDE
# the request path (a BackgroundTask after a pending read), same discipline as
# the track map. Opens its own session. Tests override with a synchronous one.
class TriageClusterPrecomputer(Protocol):
    async def __call__(self, user_id: int, source: "QueueSource") -> None: ...


async def _precompute_triage_cluster(user_id: int, source: "QueueSource") -> None:
    from crate.services.triage.cluster import precompute_triage_cluster

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        if user is None:  # pragma: no cover - defensive
            return
        precompute_triage_cluster(session, user, source)


def get_triage_cluster_precomputer() -> TriageClusterPrecomputer:
    return _precompute_triage_cluster


TriageClusterPrecomputerDep = Annotated[
    TriageClusterPrecomputer, Depends(get_triage_cluster_precomputer)
]


def get_auth_gateway() -> SpotifyAuthGateway:
    settings = get_settings()
    return SpotifyAuthGateway(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
    )
