"""Spotify OAuth connect/callback route tests — offline via a stub gateway."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_auth_gateway, get_current_user
from crate.model.enums import CredentialStatus
from crate.model.orm import SpotifyCredential, User
from crate.services.crypto import get_cipher
from crate.services.spotify.models import SpotifyUser, TokenResponse

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "spotify"
TOKEN_FIXTURE = json.loads((FIXTURES / "token_response.json").read_text())


class StubGateway:
    def __init__(self) -> None:
        self.exchanged: list[tuple[str, str]] = []

    async def exchange(self, code: str, code_verifier: str) -> TokenResponse:
        self.exchanged.append((code, code_verifier))
        return TokenResponse.model_validate(TOKEN_FIXTURE)

    async def fetch_profile(self, access_token: str) -> SpotifyUser:
        return SpotifyUser(id="spotify-jt-new", display_name="JT")


@pytest.fixture
def gateway() -> StubGateway:
    return StubGateway()


@pytest.fixture
def client(session: Session, user: User, gateway: StubGateway) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_auth_gateway] = lambda: gateway
    return TestClient(app)


def test_connect_redirects_to_spotify_with_pkce(client: TestClient) -> None:
    response = client.get("/v1/auth/spotify/connect", follow_redirects=False)
    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    params = parse_qs(location.query)
    assert location.hostname == "accounts.spotify.com"
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"][0]
    assert "playlist-modify-private" in params["scope"][0]
    assert "crate_spotify_auth" in response.cookies


def test_callback_stores_encrypted_credential(
    client: TestClient, session: Session, user: User, gateway: StubGateway
) -> None:
    connect = client.get("/v1/auth/spotify/connect", follow_redirects=False)
    state = parse_qs(urlparse(connect.headers["location"]).query)["state"][0]

    response = client.get(
        "/v1/auth/spotify/callback", params={"code": "auth-code-1", "state": state}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert response.json()["spotify_user_id"] == "spotify-jt-new"

    assert gateway.exchanged and gateway.exchanged[0][0] == "auth-code-1"

    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).one()
    assert credential.status == CredentialStatus.active
    # Stored encrypted, decryptable with the app cipher, never plaintext.
    assert credential.refresh_token_encrypted != TOKEN_FIXTURE["refresh_token"]
    assert (
        get_cipher().decrypt(credential.refresh_token_encrypted) == (TOKEN_FIXTURE["refresh_token"])
    )
    assert credential.access_token_expires_at is not None

    session.refresh(user)
    assert user.spotify_user_id == "spotify-jt-new"


def test_callback_reconnect_replaces_credential_and_clears_reauth(
    client: TestClient, session: Session, user: User
) -> None:
    session.add(
        SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted="stale",
            status=CredentialStatus.needs_reauth,
        )
    )
    session.commit()

    connect = client.get("/v1/auth/spotify/connect", follow_redirects=False)
    state = parse_qs(urlparse(connect.headers["location"]).query)["state"][0]
    response = client.get(
        "/v1/auth/spotify/callback", params={"code": "auth-code-2", "state": state}
    )
    assert response.status_code == 200

    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user.id)
    ).one()
    assert credential.status == CredentialStatus.active
    assert credential.refresh_token_encrypted != "stale"


def test_callback_state_mismatch_is_rejected(client: TestClient) -> None:
    client.get("/v1/auth/spotify/connect", follow_redirects=False)
    response = client.get(
        "/v1/auth/spotify/callback", params={"code": "auth-code-1", "state": "forged"}
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "SPOTIFY_AUTH_STATE_INVALID"


def test_callback_without_cookie_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/v1/auth/spotify/callback", params={"code": "auth-code-1", "state": "abc"}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "SPOTIFY_AUTH_STATE_INVALID"


def test_callback_user_denied_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/auth/spotify/callback", params={"error": "access_denied"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "SPOTIFY_AUTH_DENIED"


def test_playback_token_requires_connection(client: TestClient) -> None:
    response = client.get("/v1/auth/spotify/token")
    assert response.status_code == 409
    assert response.json()["error_code"] == "SPOTIFY_NOT_CONNECTED"


def test_playback_token_serves_fresh_stored_token(
    client: TestClient, session: Session, user: User
) -> None:
    from datetime import timedelta

    from crate.model.orm.base import utcnow
    from crate.services.crypto import get_cipher

    cipher = get_cipher()
    session.add(
        SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted=cipher.encrypt("refresh-token"),
            access_token_encrypted=cipher.encrypt("live-access-token"),
            access_token_expires_at=utcnow() + timedelta(minutes=30),
        )
    )
    session.commit()

    response = client.get("/v1/auth/spotify/token")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "live-access-token"
    assert body["expires_at"] is not None
    assert body["_links"]["self"]["href"] == "/v1/auth/spotify/token"
