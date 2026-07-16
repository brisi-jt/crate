"""Deezer client: no-auth 30-second track previews.

Discovery candidates get their audition audio from here — a search per
(title, artist), cached so repeated queue builds never re-fetch. Only a
result whose artist matches is accepted, so a cover version can never supply
the preview for the real track.
"""

import asyncio
from typing import Any

import httpx

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.models import ArtistTopTrack, DeezerTrack
from crate.services.enrichment.throttle import RateLimiter, Sleep, request_with_backoff

BASE_URL = "https://api.deezer.com"

# Four requests per second — polite for an unauthenticated public API.
MIN_INTERVAL_SECONDS = 0.25


class DeezerClient:
    def __init__(
        self,
        *,
        cache: ResponseCache,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
        sleep: Sleep = asyncio.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        self._cache = cache
        self._limiter = limiter or RateLimiter(min_interval=MIN_INTERVAL_SECONDS)
        self._sleep = sleep
        self._base_url = base_url
        self._http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search_preview(
        self, title: str, artist: str, *, force: bool = False
    ) -> DeezerTrack | None:
        """The first same-artist search result that carries a preview URL.

        None when Deezer has no match by this artist (or no preview for it) —
        the deck then offers the open-in-Spotify path instead of wrong audio.

        ``force`` re-fetches from Deezer even on a cache hit and drops the stale
        entry first — used by preview refresh, since a preview URL expires
        ~20 min after issue so a cached hit would return a dead URL.
        """
        query = f'track:"{title}" artist:"{artist}"'
        cache_key = f"search:{query.lower()}"
        if force:
            self._cache.invalidate(cache_key)
        payload = None if force else self._cache.get(cache_key)
        if payload is None:
            response = await request_with_backoff(
                self._http,
                "GET",
                f"{self._base_url}/search",
                params={"q": query},
                limiter=self._limiter,
                sleep=self._sleep,
            )
            response.raise_for_status()
            payload = response.json()
            self._cache.put(cache_key, payload)

        wanted = artist.strip().lower()
        items: list[dict[str, Any]] = payload.get("data", [])
        for item in items:
            result = DeezerTrack.model_validate(item)
            result.artist_name = str(item.get("artist", {}).get("name", ""))
            if result.preview and result.artist_name.strip().lower() == wanted:
                return result
        return None

    async def get_artist_top_tracks(
        self, artist_name: str, limit: int = 10
    ) -> list[ArtistTopTrack]:
        """The artist's best-known tracks, from a search over their name.

        Deezer orders search results by popularity, so the first distinct
        titles by the exact artist are its top tracks. Results by other
        artists (covers, tributes) are dropped.
        """
        query = f'artist:"{artist_name}"'
        cache_key = f"artist-top:{query.lower()}"
        payload = self._cache.get(cache_key)
        if payload is None:
            response = await request_with_backoff(
                self._http,
                "GET",
                f"{self._base_url}/search",
                params={"q": query},
                limiter=self._limiter,
                sleep=self._sleep,
            )
            response.raise_for_status()
            payload = response.json()
            self._cache.put(cache_key, payload)

        wanted = artist_name.strip().lower()
        seen: set[str] = set()
        tracks: list[ArtistTopTrack] = []
        for item in payload.get("data", []):
            name = str(item.get("artist", {}).get("name", ""))
            title = str(item.get("title", ""))
            if not title or name.strip().lower() != wanted:
                continue
            title_key = title.casefold()
            if title_key in seen:
                continue
            seen.add(title_key)
            tracks.append(ArtistTopTrack(name=title, artist_name=name))
            if len(tracks) == limit:
                break
        return tracks
