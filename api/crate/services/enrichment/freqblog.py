"""FreqBlog audio-features client — the fallback when ReccoBeats misses.

FreqBlog allows a fixed number of lookups per month; every call is metered
through try_consume_budget so the pipeline hard-stops at the allowance
instead of failing mid-month.
"""

import asyncio
from typing import Any

import httpx
from sqlmodel import Session, select

from crate.model.orm import FreqBlogBudget
from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.models import AudioFeatures
from crate.services.enrichment.throttle import RateLimiter, Sleep, request_with_backoff

BASE_URL = "https://api.freq.blog"

# One request per second — conservative; FreqBlog publishes no hard rate.
MIN_INTERVAL_SECONDS = 1.0


def try_consume_budget(session: Session, *, month: str, limit: int) -> bool:
    """Claim one lookup from the month's allowance; False when exhausted."""
    row = session.exec(select(FreqBlogBudget).where(FreqBlogBudget.month == month)).first()
    if row is None:
        row = FreqBlogBudget(month=month, used=0)
    if row.used >= limit:
        return False
    row.used += 1
    session.add(row)
    session.commit()
    return True


class FreqBlogClient:
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
        self._cache = cache
        self._limiter = limiter or RateLimiter(min_interval=MIN_INTERVAL_SECONDS)
        self._sleep = sleep
        self._base_url = base_url
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(20.0),
            headers={"X-API-Key": api_key},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_audio_features(self, spotify_id: str) -> AudioFeatures | None:
        """Features for one track; cached responses cost no budget or request."""
        cache_key = f"audio-features:{spotify_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return AudioFeatures.model_validate(cached)
        response = await request_with_backoff(
            self._http,
            "GET",
            f"{self._base_url}/v1/audio-features/{spotify_id}",
            limiter=self._limiter,
            sleep=self._sleep,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        self._cache.put(cache_key, payload)
        return AudioFeatures.model_validate(payload)
