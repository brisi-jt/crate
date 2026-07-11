"""Last.fm client: artist similarity and folksonomy tags."""

import asyncio
from typing import Any

import httpx

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.models import ArtistTagView, SimilarArtist
from crate.services.enrichment.throttle import RateLimiter, Sleep, request_with_backoff

BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Five requests per second.
MIN_INTERVAL_SECONDS = 0.2


class LastFmClient:
    def __init__(
        self,
        *,
        api_key: str,
        cache: ResponseCache,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
        sleep: Sleep = asyncio.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._cache = cache
        self._limiter = limiter or RateLimiter(min_interval=MIN_INTERVAL_SECONDS)
        self._sleep = sleep
        self._base_url = base_url
        self._http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, cache_key: str, **params: str) -> dict[str, Any]:
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        response = await request_with_backoff(
            self._http,
            "GET",
            self._base_url,
            params={"method": method, "api_key": self._api_key, "format": "json", **params},
            limiter=self._limiter,
            sleep=self._sleep,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        self._cache.put(cache_key, payload)
        return payload

    async def get_similar_artists(self, artist_name: str) -> list[SimilarArtist]:
        payload = await self._call(
            "artist.getSimilar",
            f"artist.getSimilar:{artist_name.lower()}",
            artist=artist_name,
        )
        entries = payload.get("similarartists", {}).get("artist", [])
        similar = []
        for entry in entries:
            parsed = SimilarArtist.model_validate(entry)
            if not parsed.mbid:  # Last.fm sends "" for artists without an MBID
                parsed.mbid = None
            similar.append(parsed)
        return similar

    async def get_artist_top_tags(self, artist_name: str) -> list[ArtistTagView]:
        payload = await self._call(
            "artist.getTopTags",
            f"artist.getTopTags:{artist_name.lower()}",
            artist=artist_name,
        )
        entries = payload.get("toptags", {}).get("tag", [])
        return [ArtistTagView.model_validate(entry) for entry in entries]

    async def get_track_top_tags(self, artist_name: str, track_name: str) -> list[ArtistTagView]:
        payload = await self._call(
            "track.getTopTags",
            f"track.getTopTags:{artist_name.lower()}:{track_name.lower()}",
            artist=artist_name,
            track=track_name,
        )
        entries = payload.get("toptags", {}).get("tag", [])
        return [ArtistTagView.model_validate(entry) for entry in entries]
