"""Request pacing and 429 backoff shared by the enrichment clients.

Clock and sleep are injectable so tests drive time manually — no real
sleeping in the unit suite.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

# Wait applied to a retryable response that carries no Retry-After header.
DEFAULT_BACKOFF_SECONDS = 1.0

# 429 plus the transient 5xx family. MusicBrainz signals overload with a plain
# 503, so a single hiccup must not surface as an error to the caller.
RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})


class RateLimiter:
    """Spaces calls at least min_interval seconds apart."""

    def __init__(
        self,
        *,
        min_interval: float,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None

    async def wait(self) -> None:
        """Block until the next call is allowed, then claim the slot."""
        if self._last_call is not None:
            elapsed = self._clock() - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                await self._sleep(remaining)
        self._last_call = self._clock()


async def request_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: RateLimiter,
    sleep: Sleep = asyncio.sleep,
    max_retries: int = 5,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a paced request, retrying 429s and transient 5xxs per Retry-After.

    Returns the final response even if it is still retryable after max_retries —
    callers decide how a persistent rate limit or outage surfaces.
    """
    retries = 0
    while True:
        await limiter.wait()
        response = await client.request(method, url, **kwargs)
        if response.status_code not in RETRYABLE_STATUSES or retries >= max_retries:
            return response
        retries += 1
        retry_after = response.headers.get("Retry-After")
        await sleep(float(retry_after) if retry_after else DEFAULT_BACKOFF_SECONDS)
