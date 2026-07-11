"""FreqBlog fallback client: keyed requests, caching, miss handling."""

import json
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.freqblog import FreqBlogClient
from crate.services.enrichment.throttle import RateLimiter

pytestmark = pytest.mark.unit

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/freqblog/audio_features_single.json").read_text()
)


def make_handler(request_log: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        if request.url.path.endswith(f"/{FIXTURE['id']}"):
            return httpx.Response(200, json=FIXTURE)
        return httpx.Response(404, json={"error": "not found"})

    return handler


def make_client(session: Session, handler) -> FreqBlogClient:
    return FreqBlogClient(
        api_key="freq-key",
        cache=ResponseCache(session, source="freqblog"),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(min_interval=0.0),
    )


async def test_features_fetched_for_known_track(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    features = await client.get_audio_features(FIXTURE["id"])

    assert features is not None
    assert features.energy == pytest.approx(FIXTURE["energy"])
    assert requests[0].headers["X-API-Key"] == "freq-key"
    await client.aclose()


async def test_miss_returns_none(session: Session) -> None:
    client = make_client(session, make_handler([]))
    assert await client.get_audio_features("0doesNotExist000000000") is None
    await client.aclose()


async def test_repeat_lookups_come_from_cache(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.get_audio_features(FIXTURE["id"])
    again = await client.get_audio_features(FIXTURE["id"])

    assert len(requests) == 1
    assert again is not None
    assert again.valence == pytest.approx(FIXTURE["valence"])
    await client.aclose()
