"""ReccoBeats client against the recorded Phase 0 fixture.

The recorded batch response returns items in arbitrary order, so matching is
by the Spotify ID embedded in each item's href — never by position.
"""

import json
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.reccobeats import BATCH_SIZE, ReccoBeatsClient
from crate.services.enrichment.throttle import RateLimiter

pytestmark = pytest.mark.unit

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/reccobeats/audio_features_batch.json").read_text()
)
ITEMS = FIXTURE["content"]


def spotify_id_of(item: dict) -> str:
    return item["href"].rsplit("/", 1)[-1]


def make_handler(request_log: list[httpx.Request]):
    """Serve fixture items whose href-ID is among the requested ids."""

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        requested = set(request.url.params.get("ids", "").split(","))
        matched = [
            item
            for item in ITEMS
            if spotify_id_of(item) in requested or item.get("isrc") in requested
        ]
        return httpx.Response(200, json={"content": matched})

    return handler


class NullLimiter(RateLimiter):
    def __init__(self) -> None:
        super().__init__(min_interval=0.0)


def make_client(session: Session, handler) -> ReccoBeatsClient:
    return ReccoBeatsClient(
        cache=ResponseCache(session, source="reccobeats"),
        transport=httpx.MockTransport(handler),
        limiter=NullLimiter(),
    )


async def test_batch_matches_items_by_href_not_position(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))
    # Request in reverse fixture order to prove position is irrelevant.
    ids = [spotify_id_of(item) for item in ITEMS[:5]][::-1]

    result = await client.get_audio_features_batch(ids)

    assert set(result) == set(ids)
    for item in ITEMS[:5]:
        assert result[spotify_id_of(item)].energy == pytest.approx(item["energy"])
    await client.aclose()


async def test_batch_reports_misses_as_absent_keys(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))
    known = spotify_id_of(ITEMS[0])

    result = await client.get_audio_features_batch([known, "0unknownUnknownUnknown"])

    assert set(result) == {known}
    await client.aclose()


async def test_large_requests_are_chunked(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))
    ids = [f"fake{i:018d}" for i in range(BATCH_SIZE + 5)]

    await client.get_audio_features_batch(ids)

    assert len(requests) == 2
    first_batch = requests[0].url.params.get("ids", "").split(",")
    assert len(first_batch) == BATCH_SIZE
    await client.aclose()


async def test_cached_tracks_are_not_refetched(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))
    ids = [spotify_id_of(item) for item in ITEMS[:3]]

    first = await client.get_audio_features_batch(ids)
    second = await client.get_audio_features_batch(ids)

    assert len(requests) == 1  # second call was served entirely from cache
    assert {k: v.energy for k, v in first.items()} == {k: v.energy for k, v in second.items()}
    await client.aclose()


async def test_partial_cache_only_fetches_the_gap(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))
    ids = [spotify_id_of(item) for item in ITEMS[:4]]

    await client.get_audio_features_batch(ids[:2])
    await client.get_audio_features_batch(ids)

    assert len(requests) == 2
    second_requested = requests[1].url.params.get("ids", "").split(",")
    assert set(second_requested) == set(ids[2:])
    await client.aclose()


async def test_isrc_fallback_returns_single_track(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_handler(requests))
    item = ITEMS[0]

    features = await client.get_audio_features_by_isrc(item["isrc"])

    assert features is not None
    assert features.energy == pytest.approx(item["energy"])
    await client.aclose()


async def test_isrc_fallback_miss_returns_none(session: Session) -> None:
    client = make_client(session, make_handler([]))
    assert await client.get_audio_features_by_isrc("ZZZ00000000") is None
    await client.aclose()


async def test_batch_calls_are_paced(session: Session) -> None:
    """Consecutive chunk fetches respect the two-requests-per-second limit."""
    sleeps: list[float] = []
    now = {"t": 0.0}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds

    limiter = RateLimiter(min_interval=0.5, clock=lambda: now["t"], sleep=fake_sleep)
    client = ReccoBeatsClient(
        cache=ResponseCache(session, source="reccobeats"),
        transport=httpx.MockTransport(make_handler([])),
        limiter=limiter,
    )
    ids = [f"fake{i:018d}" for i in range(BATCH_SIZE * 2)]
    await client.get_audio_features_batch(ids)

    assert sleeps == [pytest.approx(0.5)]
    await client.aclose()


# -- track recommendations ------------------------------------------------------

RECOMMENDATION_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/reccobeats/track_recommendation.json").read_text()
)


def make_recommendation_handler(request_log: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        assert request.url.path == "/v1/track/recommendation"
        return httpx.Response(200, json=RECOMMENDATION_FIXTURE)

    return handler


async def test_track_recommendation_parses_titles_and_spotify_ids(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_recommendation_handler(requests))

    tracks = await client.get_track_recommendation(["seedA", "seedB"], size=20)

    assert [t.title for t in tracks] == ["Innerbloom", "Opus"]
    assert tracks[0].spotify_id == "2GLDGkTOStFCCJDKlEBnMs"
    assert tracks[0].artist_names == ["RÜFÜS DU SOL"]
    assert tracks[0].isrc == "AUUM71500123"
    assert tracks[1].duration_ms == 540000
    params = requests[0].url.params
    assert params["seeds"] == "seedA,seedB"
    assert params["size"] == "20"
    await client.aclose()


async def test_track_recommendation_caps_seeds_at_five(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_recommendation_handler(requests))

    await client.get_track_recommendation([f"s{i}" for i in range(9)], size=10)

    assert requests[0].url.params["seeds"] == "s0,s1,s2,s3,s4"
    await client.aclose()


async def test_track_recommendation_cached_per_seed_set(session: Session) -> None:
    requests: list[httpx.Request] = []
    client = make_client(session, make_recommendation_handler(requests))

    await client.get_track_recommendation(["seedA"], size=10)
    await client.get_track_recommendation(["seedA"], size=10)
    await client.get_track_recommendation(["seedA"], size=20)  # different size = new call

    assert len(requests) == 2
    await client.aclose()
