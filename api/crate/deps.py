"""Shared FastAPI dependencies."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, select

from crate.db import get_session
from crate.errors import AppError
from crate.model.orm import RadioSession, User
from crate.services.account.wiring import AccountSyncReport, run_account_sync_for_user
from crate.services.discovery.wiring import DiscoveryReport, run_discovery
from crate.services.enrichment.orchestrator import EnrichmentReport, run_enrichment
from crate.services.mutations.wiring import spotify_writer_for_user
from crate.services.mutations.writer import SpotifyWriter
from crate.services.radio.wiring import build_radio_for_user
from crate.services.spotify.auth import SpotifyAuthGateway
from crate.services.sync import SyncReport, run_sync_for_user
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


EnrichmentRunner = Callable[[Session, int], Awaitable[EnrichmentReport]]


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


def get_auth_gateway() -> SpotifyAuthGateway:
    settings = get_settings()
    return SpotifyAuthGateway(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
    )
