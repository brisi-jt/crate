"""Shared FastAPI dependencies."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, select

from crate.db import get_session
from crate.errors import AppError
from crate.model.orm import User
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


def get_auth_gateway() -> SpotifyAuthGateway:
    settings = get_settings()
    return SpotifyAuthGateway(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
    )
