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

_FIXTURES = Path(__file__).parent / "fixtures/musicbrainz"
FIXTURE = json.loads((_FIXTURES / "isrc_lookup.json").read_text())
SEARCH_FIXTURE = json.loads((_FIXTURES / "artist_search.json").read_text())
GENRES_FIXTURE = json.loads((_FIXTURES / "artist_genres.json").read_text())


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


@pytest.mark.anyio
async def test_hyphenated_isrc_is_normalized_before_lookup(session: Session) -> None:
    """Spotify ships some ISRCs hyphen-formatted; MusicBrainz 400s that form.

    Observed live 2026-07-11: `DE-Z20-06-00039` killed a whole enrichment
    pass. Normalized (`DEZ200600039`) it is a valid lookup.
    """
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"recordings": []})

    client = make_client(session, handler)
    result = await client.lookup_isrc("de-z20-06-00039")
    assert result is None
    assert seen_paths == ["/ws/2/isrc/DEZ200600039"]
    await client.aclose()


@pytest.mark.anyio
async def test_client_error_status_is_treated_as_no_match(session: Session) -> None:
    """A 400 on one ISRC must not abort the surrounding enrichment pass."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid isrc"})

    client = make_client(session, handler)
    assert await client.lookup_isrc("NOTREALISRC1") is None
    await client.aclose()


@pytest.mark.anyio
async def test_no_match_lookups_are_negatively_cached(session: Session) -> None:
    """404 misses must not be re-queried on every enrichment pass."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"error": "not found"})

    client = make_client(session, handler)
    assert await client.lookup_isrc("GBAAA0000001") is None
    assert await client.lookup_isrc("GBAAA0000001") is None
    assert calls == 1
    await client.aclose()


# -- artist name search (MBID fallback for artists with no MB-matchable ISRC) --


def _search_handler(request_log: list[httpx.Request], body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        return httpx.Response(200, json=body)

    return handler


async def test_search_artist_returns_scored_candidates(session: Session) -> None:
    client = make_client(session, _search_handler([], SEARCH_FIXTURE))

    candidates = await client.search_artist("Kota the Friend")

    assert [(c.name, c.mbid, c.score) for c in candidates] == [
        ("Kota the Friend", "fd95384f-943b-49c1-b427-791e78242714", 100)
    ]
    await client.aclose()


async def test_search_artist_query_is_quoted_and_paced(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, _search_handler(requests, SEARCH_FIXTURE))

    await client.search_artist("Michael Franti & Spearhead")

    assert requests[0].url.path == "/ws/2/artist"
    # The name is sent as a phrase-quoted Lucene term so multi-word / punctuated
    # names don't fan out into loose token matches.
    assert requests[0].url.params["query"] == 'artist:"Michael Franti & Spearhead"'
    assert requests[0].url.params["fmt"] == "json"
    assert requests[0].headers["User-Agent"] == USER_AGENT
    await client.aclose()


async def test_search_artist_client_error_returns_empty(session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad query"})

    client = make_client(session, handler)
    assert await client.search_artist("whatever") == []
    await client.aclose()


async def test_search_artist_is_cached(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, _search_handler(requests, SEARCH_FIXTURE))

    await client.search_artist("Kota the Friend")
    await client.search_artist("Kota the Friend")

    assert len(requests) == 1
    await client.aclose()


# -- artist genres (MBID -> ENAO-shaped genre weights) ------------------------


async def test_get_artist_genres_returns_name_count_pairs(session: Session) -> None:
    client = make_client(session, _search_handler([], GENRES_FIXTURE))

    genres = await client.get_artist_genres("fd95384f-943b-49c1-b427-791e78242714")

    assert genres == [("hip hop", 5.0), ("conscious hip hop", 3.0), ("jazz rap", 1.0)]
    await client.aclose()


async def test_get_artist_genres_query_asks_for_genres_inc(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, _search_handler(requests, GENRES_FIXTURE))

    await client.get_artist_genres("fd95384f-943b-49c1-b427-791e78242714")

    assert requests[0].url.path == "/ws/2/artist/fd95384f-943b-49c1-b427-791e78242714"
    assert requests[0].url.params["inc"] == "genres"
    await client.aclose()


async def test_get_artist_genres_client_error_returns_empty(session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = make_client(session, handler)
    assert await client.get_artist_genres("00000000-0000-0000-0000-000000000000") == []
    await client.aclose()


async def test_get_artist_genres_is_cached(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, _search_handler(requests, GENRES_FIXTURE))

    await client.get_artist_genres("fd95384f-943b-49c1-b427-791e78242714")
    await client.get_artist_genres("fd95384f-943b-49c1-b427-791e78242714")

    assert len(requests) == 1
    await client.aclose()
