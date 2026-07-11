"""Deezer client: 30-second preview lookup against the recorded Phase 0 fixture."""

import json
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.deezer import DeezerClient
from crate.services.enrichment.throttle import RateLimiter

pytestmark = pytest.mark.unit

FIXTURE = json.loads((Path(__file__).parent / "fixtures/deezer/search.json").read_text())


def make_handler(request_log: list[httpx.Request], payload: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        return httpx.Response(200, json=payload if payload is not None else FIXTURE)

    return handler


def make_client(session: Session, handler) -> DeezerClient:
    return DeezerClient(
        cache=ResponseCache(session, source="deezer"),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(min_interval=0.0),
    )


async def test_search_preview_returns_matching_artist_result(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    result = await client.search_preview("Blinding Lights", "The Weeknd")

    assert result is not None
    assert result.preview.startswith("https://")
    assert result.artist_name == "The Weeknd"
    assert result.title == "Blinding Lights"
    # Advanced-search query, quoted so multi-word names stay one term.
    assert requests[0].url.params["q"] == 'track:"Blinding Lights" artist:"The Weeknd"'
    await client.aclose()


async def test_search_preview_skips_non_matching_artists(session: Session) -> None:
    """A cover by another artist must never supply the preview."""
    covers_only = {
        "data": [item for item in FIXTURE["data"] if item["artist"]["name"] != "The Weeknd"]
    }
    client = make_client(session, make_handler([], covers_only))

    assert await client.search_preview("Blinding Lights", "The Weeknd") is None
    await client.aclose()


async def test_search_preview_requires_a_preview_url(session: Session) -> None:
    no_previews = {
        "data": [{**FIXTURE["data"][0], "preview": ""}],
    }
    client = make_client(session, make_handler([], no_previews))

    assert await client.search_preview("Blinding Lights", "The Weeknd") is None
    await client.aclose()


async def test_search_preview_cached_per_query(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.search_preview("Blinding Lights", "The Weeknd")
    await client.search_preview("Blinding Lights", "The Weeknd")

    assert len(requests) == 1
    await client.aclose()
