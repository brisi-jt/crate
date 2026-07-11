"""Authorization Code + PKCE helpers and the auth-time HTTP gateway."""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from crate.services.spotify.client import (
    ACCOUNTS_AUTHORIZE_URL,
    ACCOUNTS_TOKEN_URL,
    API_BASE_URL,
    SpotifyApiError,
    SpotifyReauthRequired,
)
from crate.services.spotify.models import SpotifyUser, TokenResponse

SPOTIFY_SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-read",
    "user-library-modify",
    "user-top-read",
    "user-read-recently-played",
    "user-read-currently-playing",
    "streaming",
]


def generate_code_verifier() -> str:
    """RFC 7636 code verifier (43-128 chars from the unreserved set)."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """S256 challenge: base64url(sha256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    challenge: str,
    scopes: list[str] | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(scopes or SPOTIFY_SCOPES),
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return f"{ACCOUNTS_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    transport: httpx.BaseTransport | None = None,
) -> TokenResponse:
    """Trade an authorization code for tokens (public client, no secret)."""
    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0)) as http:
        response = await http.post(
            ACCOUNTS_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
        )
    if response.status_code in (400, 401, 403):
        raise SpotifyReauthRequired(f"Authorization code rejected ({response.status_code})")
    if response.is_error:
        raise SpotifyApiError(response.status_code, response.text)
    return TokenResponse.model_validate(response.json())


class SpotifyAuthGateway:
    """The two auth-time calls the OAuth callback needs.

    Kept as a small object so tests (and later, other identity providers) can
    swap it via dependency override.
    """

    def __init__(self, *, client_id: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._redirect_uri = redirect_uri

    async def exchange(self, code: str, code_verifier: str) -> TokenResponse:
        return await exchange_code(
            client_id=self._client_id,
            code=code,
            redirect_uri=self._redirect_uri,
            code_verifier=code_verifier,
        )

    async def fetch_profile(self, access_token: str) -> SpotifyUser:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http:
            response = await http.get(
                f"{API_BASE_URL}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.is_error:
            raise SpotifyApiError(response.status_code, response.text)
        return SpotifyUser.model_validate(response.json())
