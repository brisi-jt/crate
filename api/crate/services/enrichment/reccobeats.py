"""ReccoBeats audio-features client — the primary feature source.

Batch responses return items in arbitrary order, so each item is matched to
its track via the Spotify ID embedded in the item's href, never by position.
"""

import asyncio
from typing import Any

import httpx

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.models import AudioFeatures
from crate.services.enrichment.throttle import RateLimiter, Sleep, request_with_backoff

BASE_URL = "https://api.reccobeats.com"

# Documented maximum ids per audio-features request.
BATCH_SIZE = 40

# Two requests per second.
MIN_INTERVAL_SECONDS = 0.5


def _spotify_id_from_href(href: str | None) -> str | None:
    """The href is an open.spotify.com track URL; its last segment is the ID."""
    if not href:
        return None
    return href.rstrip("/").rsplit("/", 1)[-1] or None


class ReccoBeatsClient:
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

    async def get_audio_features_batch(self, spotify_ids: list[str]) -> dict[str, AudioFeatures]:
        """Features keyed by Spotify ID; ids the service doesn't know are absent.

        Previously fetched tracks are served from the cache; only the gap is
        requested, in chunks of BATCH_SIZE.
        """
        result: dict[str, AudioFeatures] = {}
        to_fetch: list[str] = []
        for spotify_id in spotify_ids:
            cached = self._cache.get(f"audio-features:{spotify_id}")
            if cached is not None:
                result[spotify_id] = AudioFeatures.model_validate(cached)
            else:
                to_fetch.append(spotify_id)

        for start in range(0, len(to_fetch), BATCH_SIZE):
            chunk = to_fetch[start : start + BATCH_SIZE]
            response = await request_with_backoff(
                self._http,
                "GET",
                f"{self._base_url}/v1/audio-features",
                params={"ids": ",".join(chunk)},
                limiter=self._limiter,
                sleep=self._sleep,
            )
            response.raise_for_status()
            for item in response.json().get("content", []):
                spotify_id = _spotify_id_from_href(item.get("href"))
                if spotify_id is None or spotify_id not in chunk:
                    continue
                self._cache.put(f"audio-features:{spotify_id}", item)
                result[spotify_id] = AudioFeatures.model_validate(item)
        return result

    async def get_audio_features_by_isrc(self, isrc: str) -> AudioFeatures | None:
        """Single-track lookup by ISRC — the fallback when the Spotify ID misses."""
        cache_key = f"audio-features:isrc:{isrc}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return AudioFeatures.model_validate(cached)
        response = await request_with_backoff(
            self._http,
            "GET",
            f"{self._base_url}/v1/audio-features",
            params={"ids": isrc},
            limiter=self._limiter,
            sleep=self._sleep,
        )
        response.raise_for_status()
        items: list[dict[str, Any]] = response.json().get("content", [])
        if not items:
            return None
        self._cache.put(cache_key, items[0])
        return AudioFeatures.model_validate(items[0])
