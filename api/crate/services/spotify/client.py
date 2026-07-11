"""Async Spotify Web API client.

Handles bearer auth, transparent access-token refresh (PKCE public-client
flow), 429 backoff honoring Retry-After, and cursor-free offset pagination.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from crate.model.orm.base import utcnow
from crate.services.spotify.models import (
    PlaylistTrackItem,
    SpotifyPlaylistSummary,
    SpotifyUser,
    TokenResponse,
)

API_BASE_URL = "https://api.spotify.com/v1"
ACCOUNTS_TOKEN_URL = "https://accounts.spotify.com/api/token"
ACCOUNTS_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"


class SpotifyError(Exception):
    """Base class for Spotify client failures."""


class SpotifyApiError(SpotifyError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Spotify API error {status_code}: {message}")
        self.status_code = status_code


class SpotifyReauthRequired(SpotifyError):
    """The refresh token was rejected — the user must re-consent."""


class SpotifyClient:
    def __init__(
        self,
        *,
        client_id: str,
        refresh_token: str,
        access_token: str | None = None,
        on_tokens: Callable[[str], None] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_rate_limit_retries: int = 5,
    ) -> None:
        self._client_id = client_id
        self._refresh_token = refresh_token
        self._access_token = access_token
        # Called with the current refresh token after every successful refresh,
        # so callers can re-encrypt and persist rotations.
        self._on_tokens = on_tokens
        self._sleep = sleep
        self._max_rate_limit_retries = max_rate_limit_retries
        self.access_token_expires_at: datetime | None = None
        self._http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0))

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _refresh_access_token(self) -> None:
        response = await self._http.post(
            ACCOUNTS_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
        )
        if response.status_code in (400, 401, 403):
            raise SpotifyReauthRequired(
                f"Spotify rejected the refresh token ({response.status_code})"
            )
        if response.is_error:
            raise SpotifyApiError(response.status_code, response.text)
        tokens = TokenResponse.model_validate(response.json())
        self._access_token = tokens.access_token
        self.access_token_expires_at = utcnow() + timedelta(seconds=tokens.expires_in)
        if tokens.refresh_token:
            self._refresh_token = tokens.refresh_token
        if self._on_tokens is not None:
            self._on_tokens(self._refresh_token)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        refreshed = False
        rate_limit_retries = 0
        while True:
            if self._access_token is None:
                await self._refresh_access_token()
            response = await self._http.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                **kwargs,
            )
            if response.status_code == 401 and not refreshed:
                refreshed = True
                self._access_token = None
                continue
            if response.status_code == 429 and rate_limit_retries < self._max_rate_limit_retries:
                rate_limit_retries += 1
                await self._sleep(float(response.headers.get("Retry-After", "1")))
                continue
            if response.is_error:
                raise SpotifyApiError(response.status_code, response.text)
            return response

    async def _iter_pages(
        self, first_url: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield paging objects, following absolute `next` URLs to the end."""
        url: str | None = first_url
        page_params = params
        while url:
            response = await self._request("GET", url, params=page_params)
            page_params = None  # `next` URLs already carry their query string
            page: dict[str, Any] = response.json()
            yield page
            url = page.get("next")

    async def get_current_user(self) -> SpotifyUser:
        response = await self._request("GET", f"{API_BASE_URL}/me")
        return SpotifyUser.model_validate(response.json())

    async def iter_playlists(self) -> AsyncIterator[SpotifyPlaylistSummary]:
        """All playlists in the user's library (owned and followed)."""
        async for page in self._iter_pages(f"{API_BASE_URL}/me/playlists", params={"limit": 50}):
            for item in page.get("items", []):
                yield SpotifyPlaylistSummary.model_validate(item)

    async def iter_playlist_tracks(self, playlist_id: str) -> AsyncIterator[PlaylistTrackItem]:
        """A playlist's full track listing in playlist order."""
        async for page in self._iter_pages(
            f"{API_BASE_URL}/playlists/{playlist_id}/tracks", params={"limit": 100}
        ):
            for item in page.get("items", []):
                yield PlaylistTrackItem.model_validate(item)

    # -- writes ------------------------------------------------------------

    _WRITE_CHUNK = 100  # Spotify's per-call cap on playlist item operations

    async def list_track_uris(self, playlist_id: str) -> list[str]:
        """The playlist's current track URIs in playlist order."""
        uris: list[str] = []
        async for page in self._iter_pages(
            f"{API_BASE_URL}/playlists/{playlist_id}/tracks", params={"limit": 100}
        ):
            for item in page.get("items", []):
                track = item.get("track") or {}
                uri = track.get("uri")
                if uri:
                    uris.append(uri)
        return uris

    async def add_playlist_tracks(
        self, playlist_id: str, uris: list[str], position: int | None = None
    ) -> str:
        """Add tracks (chunked at the API's 100-URI cap). Returns the new snapshot id."""
        snapshot = ""
        for offset in range(0, len(uris), self._WRITE_CHUNK):
            chunk = uris[offset : offset + self._WRITE_CHUNK]
            body: dict[str, Any] = {"uris": chunk}
            if position is not None:
                body["position"] = position + offset
            response = await self._request(
                "POST", f"{API_BASE_URL}/playlists/{playlist_id}/tracks", json=body
            )
            snapshot = response.json().get("snapshot_id", "")
        return snapshot

    async def remove_playlist_tracks(self, playlist_id: str, uris: list[str]) -> str:
        """Remove every occurrence of each URI. Returns the new snapshot id."""
        snapshot = ""
        for offset in range(0, len(uris), self._WRITE_CHUNK):
            chunk = uris[offset : offset + self._WRITE_CHUNK]
            response = await self._request(
                "DELETE",
                f"{API_BASE_URL}/playlists/{playlist_id}/tracks",
                json={"tracks": [{"uri": uri} for uri in chunk]},
            )
            snapshot = response.json().get("snapshot_id", "")
        return snapshot

    async def reorder_playlist_range(
        self,
        playlist_id: str,
        *,
        range_start: int,
        insert_before: int,
        range_length: int = 1,
    ) -> str:
        """Move a range of items (indices refer to the pre-move listing)."""
        response = await self._request(
            "PUT",
            f"{API_BASE_URL}/playlists/{playlist_id}/tracks",
            json={
                "range_start": range_start,
                "insert_before": insert_before,
                "range_length": range_length,
            },
        )
        return response.json().get("snapshot_id", "")

    async def create_playlist(self, name: str, description: str | None = None) -> tuple[str, str]:
        """Create a private playlist. Returns (spotify_id, snapshot_id)."""
        me = await self.get_current_user()
        body: dict[str, Any] = {"name": name, "public": False}
        if description:
            body["description"] = description
        response = await self._request("POST", f"{API_BASE_URL}/users/{me.id}/playlists", json=body)
        payload = response.json()
        return payload["id"], payload.get("snapshot_id", "")

    async def change_playlist_details(
        self,
        playlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Update name and/or description; omitted fields keep their value."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if not body:
            return
        await self._request("PUT", f"{API_BASE_URL}/playlists/{playlist_id}", json=body)

    async def unfollow_playlist(self, playlist_id: str) -> None:
        """Remove the playlist from the library (Spotify's closest thing to delete)."""
        await self._request("DELETE", f"{API_BASE_URL}/playlists/{playlist_id}/followers")
