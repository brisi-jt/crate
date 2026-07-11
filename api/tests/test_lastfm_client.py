"""Last.fm client: similar artists and top tags, fixture-driven."""

import json
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.lastfm import LastFmClient
from crate.services.enrichment.throttle import RateLimiter

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures/lastfm"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def make_handler(request_log: list[httpx.Request]):
    responses = {
        "artist.getsimilar": load("artist_get_similar.json"),
        "artist.gettoptags": load("artist_get_top_tags.json"),
        "track.gettoptags": load("track_get_top_tags.json"),
        "artist.gettoptracks": load("artist_get_top_tracks.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        method = request.url.params.get("method", "").lower()
        if method not in responses:
            return httpx.Response(400, json={"error": 6, "message": "Invalid method"})
        return httpx.Response(200, json=responses[method])

    return handler


def make_client(session: Session, handler) -> LastFmClient:
    return LastFmClient(
        api_key="test-key",
        cache=ResponseCache(session, source="lastfm"),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(min_interval=0.0),
    )


async def test_similar_artists_parsed_with_weights(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    similar = await client.get_similar_artists("Tycho")

    assert [s.name for s in similar] == ["Boards of Canada", "Aphex Twin", "Bibio"]
    assert similar[0].match == pytest.approx(1.0)
    assert similar[1].mbid == "f22942a1-6f70-4f48-866e-238cb2308fbd"
    assert similar[2].mbid is None  # empty-string mbid normalized away
    await client.aclose()


async def test_requests_carry_api_key_and_json_format(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.get_similar_artists("Tycho")

    params = requests[0].url.params
    assert params["api_key"] == "test-key"
    assert params["format"] == "json"
    assert params["artist"] == "Tycho"
    await client.aclose()


async def test_artist_top_tags_parsed(session: Session) -> None:
    client = make_client(session, make_handler([]))
    tags = await client.get_artist_top_tags("Tycho")
    assert tags[0].name == "electronic"
    assert tags[0].count == 100
    assert len(tags) == 4
    await client.aclose()


async def test_track_top_tags_parsed(session: Session) -> None:
    client = make_client(session, make_handler([]))
    tags = await client.get_track_top_tags("Tycho", "Awake")
    assert [t.name for t in tags] == ["electronic", "downtempo"]
    await client.aclose()


async def test_artist_top_tracks_parsed(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    tracks = await client.get_artist_top_tracks("Boards of Canada")

    assert [t.name for t in tracks] == ["Dayvan Cowboy", "Roygbiv", "Olson"]
    assert tracks[0].artist_name == "Boards of Canada"
    assert tracks[0].mbid == "3a94a17c-937a-4c15-8c48-b8a7b3f1a5b2"
    assert tracks[1].mbid is None  # empty-string mbid normalized away
    params = requests[0].url.params
    assert params["method"] == "artist.getTopTracks"
    assert params["limit"] == "10"
    await client.aclose()


async def test_artist_top_tracks_cached(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.get_artist_top_tracks("Boards of Canada")
    await client.get_artist_top_tracks("Boards of Canada")

    assert len(requests) == 1
    await client.aclose()


async def test_responses_are_cached_per_artist(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))

    await client.get_similar_artists("Tycho")
    await client.get_similar_artists("Tycho")
    await client.get_artist_top_tags("Tycho")
    await client.get_artist_top_tags("Tycho")

    assert len(requests) == 2  # one per distinct method, repeats served from cache
    await client.aclose()


async def test_calls_are_paced_at_five_per_second(session: Session) -> None:
    sleeps: list[float] = []
    now = {"t": 0.0}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds

    client = LastFmClient(
        api_key="test-key",
        cache=ResponseCache(session, source="lastfm"),
        transport=httpx.MockTransport(make_handler([])),
        limiter=RateLimiter(min_interval=0.2, clock=lambda: now["t"], sleep=fake_sleep),
    )
    await client.get_similar_artists("A")
    await client.get_artist_top_tags("A")

    assert sleeps == [pytest.approx(0.2)]
    await client.aclose()
