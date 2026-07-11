"""MusicBrainz client: ISRC→recording/artist MBID resolution, fixture-driven."""

import json
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.musicbrainz import USER_AGENT, MusicBrainzClient
from crate.services.enrichment.throttle import RateLimiter

pytestmark = pytest.mark.unit

FIXTURE = json.loads((Path(__file__).parent / "fixtures/musicbrainz/isrc_lookup.json").read_text())


def make_handler(request_log: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        if request.url.path.endswith("/USSM11912587"):
            return httpx.Response(200, json=FIXTURE)
        return httpx.Response(404, json={"error": "Not Found"})

    return handler


def make_client(session: Session, handler) -> MusicBrainzClient:
    return MusicBrainzClient(
        cache=ResponseCache(session, source="musicbrainz"),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(min_interval=0.0),
    )


async def test_isrc_resolves_recording_and_artist_mbids(session: Session) -> None:
    client = make_client(session, make_handler([]))

    recording = await client.lookup_isrc("USSM11912587")

    assert recording is not None
    assert recording.recording_mbid == "3f7f47a8-2f6e-4c0c-9d3b-1f7a2b6c5d4e"
    assert recording.artist_credits == [("Post Malone", "b1e26560-60e5-4236-bbdb-9aa5a8d5ee19")]
    await client.aclose()


async def test_unknown_isrc_returns_none(session: Session) -> None:
    client = make_client(session, make_handler([]))
    assert await client.lookup_isrc("ZZZ00000000") is None
    await client.aclose()


async def test_requests_send_identifying_user_agent(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.lookup_isrc("USSM11912587")

    assert requests[0].headers["User-Agent"] == USER_AGENT
    assert USER_AGENT == "crate/0.1 (personal project)"
    await client.aclose()


async def test_lookups_are_cached(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.lookup_isrc("USSM11912587")
    await client.lookup_isrc("USSM11912587")

    assert len(requests) == 1
    await client.aclose()


async def test_calls_are_paced_at_one_per_second(session: Session) -> None:
    sleeps: list[float] = []
    now = {"t": 0.0}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds

    client = MusicBrainzClient(
        cache=ResponseCache(session, source="musicbrainz"),
        transport=httpx.MockTransport(make_handler([])),
        limiter=RateLimiter(min_interval=1.0, clock=lambda: now["t"], sleep=fake_sleep),
    )
    await client.lookup_isrc("USSM11912587")
    await client.lookup_isrc("ZZZ00000000")

    assert sleeps == [pytest.approx(1.0)]
    await client.aclose()
