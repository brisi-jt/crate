"""MusicBrainz client: the ID spine linking ISRCs to recording/artist MBIDs.

MusicBrainz requires a meaningful User-Agent and allows roughly one request
per second for anonymous clients.
"""

import asyncio

import httpx

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.models import IsrcRecording
from crate.services.enrichment.throttle import RateLimiter, Sleep, request_with_backoff

BASE_URL = "https://musicbrainz.org/ws/2"

USER_AGENT = "crate/0.1 (personal project)"

MIN_INTERVAL_SECONDS = 1.0


class MusicBrainzClient:
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
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": USER_AGENT},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def lookup_isrc(self, isrc: str) -> IsrcRecording | None:
        """Resolve an ISRC to its first recording and that recording's artists.

        ISRCs arrive in the wild both bare (DEZ200600039) and hyphenated
        (DE-Z20-06-00039); MusicBrainz only accepts the bare form. Any 4xx is
        a no-match for that ISRC, never an error for the caller — one bad
        identifier must not abort a whole enrichment pass. Misses are cached
        as empty recording lists so they aren't re-queried every pass. A 5xx
        that survives the backoff retries raises HTTPStatusError and is NOT
        cached — the outage is MusicBrainz's state, not the ISRC's.
        """
        normalized = isrc.replace("-", "").replace(" ", "").upper()
        cache_key = f"isrc:{normalized}"
        cached = self._cache.get(cache_key)
        if cached is None:
            response = await request_with_backoff(
                self._http,
                "GET",
                f"{self._base_url}/isrc/{normalized}",
                params={"fmt": "json", "inc": "artist-credits"},
                limiter=self._limiter,
                sleep=self._sleep,
            )
            if 400 <= response.status_code < 500:
                cached = {"recordings": []}
                self._cache.put(cache_key, cached)
                return None
            response.raise_for_status()
            cached = response.json()
            self._cache.put(cache_key, cached)

        recordings = cached.get("recordings", [])
        if not recordings:
            return None
        recording = recordings[0]
        credits = [
            (credit["artist"]["name"], credit["artist"]["id"])
            for credit in recording.get("artist-credit", [])
            if credit.get("artist", {}).get("id")
        ]
        return IsrcRecording(recording_mbid=recording["id"], artist_credits=credits)
