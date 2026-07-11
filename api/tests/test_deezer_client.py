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


# -------------------------------------------------------- artist top tracks

ARTIST_SEARCH = {
    "data": [
        {"id": 1, "title": "Magical", "preview": "https://cdn/p1", "artist": {"name": "Cassian"}},
        {"id": 2, "title": "Magical", "preview": "https://cdn/p1b", "artist": {"name": "Cassian"}},
        {"id": 3, "title": "Same Things", "preview": "", "artist": {"name": "Cassian"}},
        {
            "id": 4,
            "title": "Not Him",
            "preview": "https://cdn/p2",
            "artist": {"name": "Cassian Cover Band"},
        },
        {"id": 5, "title": "Lafayette", "preview": "https://cdn/p3", "artist": {"name": "Cassian"}},
    ]
}


async def test_artist_top_tracks_filters_artist_and_dedupes_titles(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests, ARTIST_SEARCH))

    tracks = await client.get_artist_top_tracks("Cassian", limit=10)

    assert [(t.name, t.artist_name) for t in tracks] == [
        ("Magical", "Cassian"),
        ("Same Things", "Cassian"),
        ("Lafayette", "Cassian"),
    ]
    assert requests[0].url.params["q"] == 'artist:"Cassian"'
    await client.aclose()


async def test_artist_top_tracks_respects_limit_and_caches(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests, ARTIST_SEARCH))

    first = await client.get_artist_top_tracks("Cassian", limit=2)
    second = await client.get_artist_top_tracks("Cassian", limit=2)

    assert [t.name for t in first] == ["Magical", "Same Things"]
    assert first == second
    assert len(requests) == 1
    await client.aclose()
