"""Spotify account connection (Authorization Code + PKCE)."""

import json
import secrets
from datetime import timedelta
from typing import Annotated, Any

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import select

from crate.deps import CurrentUserDep, SessionDep, get_auth_gateway
from crate.errors import AppError, ProblemDetail
from crate.model.enums import CredentialStatus
from crate.model.orm import SpotifyCredential, utcnow
from crate.services.crypto import get_cipher
from crate.services.spotify.auth import (
    SpotifyAuthGateway,
    build_authorize_url,
    code_challenge,
    generate_code_verifier,
)
from crate.settings import get_settings

router = APIRouter(prefix="/v1/auth/spotify", tags=["auth"])

# Short-lived cookie carrying the encrypted PKCE verifier + state between the
# redirect to Spotify and the callback.
AUTH_COOKIE = "crate_spotify_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 600

AuthGatewayDep = Annotated[SpotifyAuthGateway, Depends(get_auth_gateway)]


@router.get(
    "/connect",
    summary="Start the Spotify authorization flow",
    description=(
        "Redirects the browser to Spotify's consent page. On approval, Spotify "
        "redirects back to the callback endpoint, which stores the credential. "
        "Use this both for first-time connection and to recover a credential "
        "in the needs_reauth state."
    ),
    status_code=307,
    response_class=RedirectResponse,
)
def spotify_connect(_user: CurrentUserDep) -> RedirectResponse:
    settings = get_settings()
    verifier = generate_code_verifier()
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
        state=state,
        challenge=code_challenge(verifier),
    )
    response = RedirectResponse(url, status_code=307)
    response.set_cookie(
        AUTH_COOKIE,
        get_cipher().encrypt(json.dumps({"verifier": verifier, "state": state})),
        max_age=AUTH_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get(
    "/callback",
    summary="Complete the Spotify authorization flow",
    description=(
        "Landing point for Spotify's redirect after consent. Exchanges the "
        "authorization code for tokens, stores the refresh token encrypted, "
        "and records the account's Spotify user id."
    ),
    responses={400: {"model": ProblemDetail, "description": "Declined, expired, or forged."}},
)
async def spotify_callback(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    gateway: AuthGatewayDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> JSONResponse:
    if error:
        raise AppError(
            400,
            "Spotify authorization declined",
            detail=f"Spotify returned: {error}",
            error_code="SPOTIFY_AUTH_DENIED",
        )

    payload = _read_auth_cookie(request)
    if code is None or state is None or state != payload.get("state"):
        raise AppError(
            400,
            "Authorization state mismatch",
            detail="The state parameter does not match this session. Restart via /connect.",
            error_code="SPOTIFY_AUTH_STATE_INVALID",
        )

    tokens = await gateway.exchange(code, payload["verifier"])
    if tokens.refresh_token is None:
        raise AppError(
            400,
            "Spotify did not return a refresh token",
            detail="Restart the flow via /v1/auth/spotify/connect.",
            error_code="SPOTIFY_AUTH_NO_REFRESH_TOKEN",
        )
    profile = await gateway.fetch_profile(tokens.access_token)

    cipher = get_cipher()
    user.spotify_user_id = profile.id
    session.add(user)

    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).first()
    if credential is None:
        credential = SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted=cipher.encrypt(tokens.refresh_token),
        )
    else:
        credential.refresh_token_encrypted = cipher.encrypt(tokens.refresh_token)
    credential.access_token_encrypted = cipher.encrypt(tokens.access_token)
    credential.access_token_expires_at = utcnow() + timedelta(seconds=tokens.expires_in)
    credential.scope = tokens.scope
    credential.status = CredentialStatus.active
    session.add(credential)
    session.commit()

    response = JSONResponse(
        {
            "status": "connected",
            "spotify_user_id": profile.id,
            "_links": {
                "sync": {"href": "/v1/sync"},
                "sync_status": {"href": "/v1/sync/status"},
            },
        }
    )
    response.delete_cookie(AUTH_COOKIE)
    return response


@router.get(
    "/token",
    summary="A playback token for the Web Playback SDK",
    description=(
        "A currently-valid Spotify access token for the browser's Web "
        "Playback SDK player, refreshed server-side when the stored one is "
        "near expiry. Requires a connected Spotify account with the "
        "streaming scope."
    ),
    responses={
        409: {
            "model": ProblemDetail,
            "description": "Spotify is not connected, or the credential needs re-consent.",
        },
    },
)
async def spotify_playback_token(session: SessionDep, user: CurrentUserDep) -> dict[str, Any]:
    from crate.services.mutations.wiring import spotify_client_for_user

    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).first()
    cipher = get_cipher()
    now = utcnow()
    links = {"_links": {"self": {"href": "/v1/auth/spotify/token"}}}

    fresh_until = credential.access_token_expires_at if credential else None
    if (
        credential is not None
        and credential.status == CredentialStatus.active
        and credential.access_token_encrypted
        and fresh_until is not None
        and fresh_until > now + timedelta(seconds=60)
    ):
        return {
            "access_token": cipher.decrypt(credential.access_token_encrypted),
            "expires_at": fresh_until.isoformat(),
            **links,
        }

    # Stale or absent access token: refresh through the stored credential
    # (raises the standard 409 problems when no usable credential exists).
    async with spotify_client_for_user(session, user) as client:
        token = await client.ensure_access_token(force_refresh=True)
        expires_at = client.access_token_expires_at
    return {
        "access_token": token,
        "expires_at": expires_at.isoformat() if expires_at else None,
        **links,
    }


def _read_auth_cookie(request: Request) -> dict[str, Any]:
    cookie = request.cookies.get(AUTH_COOKIE)
    if not cookie:
        raise AppError(
            400,
            "Authorization session missing",
            detail="No in-flight authorization found. Start via /v1/auth/spotify/connect.",
            error_code="SPOTIFY_AUTH_STATE_INVALID",
        )
    try:
        return json.loads(get_cipher().decrypt(cookie))
    except (InvalidToken, ValueError) as exc:
        raise AppError(
            400,
            "Authorization session invalid",
            detail="The authorization session cookie could not be read. Restart via /connect.",
            error_code="SPOTIFY_AUTH_STATE_INVALID",
        ) from exc
