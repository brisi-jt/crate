"""The refresh preflight gate — no token endpoint call when storage is down.

Spotify rotates the refresh token whenever the token endpoint is hit, so the
client must run the caller's ``preflight`` before the POST. A raising preflight
means the endpoint is never contacted (asserted by MockTransport call count).
"""

import httpx
import pytest

from crate.services.spotify.client import SpotifyClient
from crate.services.storage import StorageUnavailable

pytestmark = pytest.mark.unit


def _refresh_client(handler, calls: list[int], preflight=None) -> SpotifyClient:
    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return handler(request)

    return SpotifyClient(
        client_id="test-client-id",
        refresh_token="stored-refresh-token",
        access_token=None,  # forces a refresh on first request
        transport=httpx.MockTransport(counting),
        preflight=preflight,
    )


async def test_refresh_skips_token_endpoint_when_preflight_raises() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        return httpx.Response(
            200, json={"access_token": "x", "token_type": "Bearer", "expires_in": 3600}
        )

    def preflight() -> None:
        raise StorageUnavailable("db down")

    client = _refresh_client(handler, calls, preflight=preflight)
    with pytest.raises(StorageUnavailable):
        await client.ensure_access_token(force_refresh=True)
    await client.aclose()

    assert calls == []  # the token endpoint was never hit → no rotation


async def test_refresh_proceeds_when_preflight_passes() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rotated-refresh",
            },
        )

    client = _refresh_client(handler, calls, preflight=lambda: None)
    token = await client.ensure_access_token(force_refresh=True)
    await client.aclose()

    assert token == "fresh-access"
    assert client.refresh_token == "rotated-refresh"
    assert calls == [1]


async def test_no_preflight_leaves_refresh_unchanged() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "a", "token_type": "Bearer", "expires_in": 3600}
        )

    client = _refresh_client(handler, calls, preflight=None)
    await client.ensure_access_token(force_refresh=True)
    await client.aclose()

    assert calls == [1]
