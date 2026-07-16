"""Rate limiter pacing and 429 backoff, driven by a fake clock (no real sleeps)."""

from itertools import pairwise

import httpx
import pytest

from crate.services.enrichment.throttle import RateLimiter, request_with_backoff

pytestmark = pytest.mark.unit


class FakeClock:
    """Manual monotonic clock; sleep() advances it and records each wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def limiter(clock: FakeClock, min_interval: float) -> RateLimiter:
    return RateLimiter(min_interval=min_interval, clock=clock.time, sleep=clock.sleep)


class TestRateLimiter:
    async def test_first_request_is_not_delayed(self, clock: FakeClock) -> None:
        rl = limiter(clock, min_interval=0.5)
        await rl.wait()
        assert clock.sleeps == []

    async def test_back_to_back_requests_are_paced_to_min_interval(self, clock: FakeClock) -> None:
        """Two req/s means consecutive calls sit at least 0.5s apart."""
        rl = limiter(clock, min_interval=0.5)
        stamps = []
        for _ in range(4):
            await rl.wait()
            stamps.append(clock.now)
        gaps = [b - a for a, b in pairwise(stamps)]
        assert all(gap >= 0.5 for gap in gaps)

    async def test_no_delay_when_caller_is_already_slower_than_limit(
        self, clock: FakeClock
    ) -> None:
        rl = limiter(clock, min_interval=0.5)
        await rl.wait()
        clock.now += 2.0  # caller spent longer than the interval elsewhere
        await rl.wait()
        assert clock.sleeps == []

    async def test_partial_elapsed_time_only_waits_the_remainder(self, clock: FakeClock) -> None:
        rl = limiter(clock, min_interval=1.0)
        await rl.wait()
        clock.now += 0.4
        await rl.wait()
        assert clock.sleeps == [pytest.approx(0.6)]


class TestBackoff:
    async def test_retries_429_honoring_retry_after(self, clock: FakeClock) -> None:
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(clock.now)
            if len(attempts) < 3:
                return httpx.Response(429, headers={"Retry-After": "7"})
            return httpx.Response(200, json={"ok": True})

        rl = limiter(clock, min_interval=0.5)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await request_with_backoff(
                client, "GET", "https://example.test/x", limiter=rl, sleep=clock.sleep
            )
        assert response.status_code == 200
        assert len(attempts) == 3
        # Both waits came from Retry-After, not a guessed default.
        assert clock.sleeps.count(7.0) == 2

    async def test_429_without_retry_after_uses_default_backoff(self, clock: FakeClock) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429)
            return httpx.Response(200, json={})

        rl = limiter(clock, min_interval=0.0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await request_with_backoff(
                client, "GET", "https://example.test/x", limiter=rl, sleep=clock.sleep
            )
        assert response.status_code == 200
        assert clock.sleeps and clock.sleeps[0] >= 1.0

    async def test_retries_503_honoring_retry_after(self, clock: FakeClock) -> None:
        """MusicBrainz signals overload with 503; it must be retried like 429."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(clock.now)
            if len(attempts) < 3:
                return httpx.Response(503, headers={"Retry-After": "5"})
            return httpx.Response(200, json={"ok": True})

        rl = limiter(clock, min_interval=0.0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await request_with_backoff(
                client, "GET", "https://example.test/x", limiter=rl, sleep=clock.sleep
            )
        assert response.status_code == 200
        assert len(attempts) == 3
        assert clock.sleeps.count(5.0) == 2

    async def test_returns_persistent_503_after_max_retries(self, clock: FakeClock) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        rl = limiter(clock, min_interval=0.0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await request_with_backoff(
                client,
                "GET",
                "https://example.test/x",
                limiter=rl,
                sleep=clock.sleep,
                max_retries=2,
            )
        assert response.status_code == 503
        assert len(clock.sleeps) == 2

    async def test_gives_up_after_max_retries(self, clock: FakeClock) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "1"})

        rl = limiter(clock, min_interval=0.0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await request_with_backoff(
                client,
                "GET",
                "https://example.test/x",
                limiter=rl,
                sleep=clock.sleep,
                max_retries=3,
            )
        assert response.status_code == 429
        assert clock.sleeps == [1.0, 1.0, 1.0]

    async def test_requests_go_through_the_limiter(self, clock: FakeClock) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        rl = limiter(clock, min_interval=0.5)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for _ in range(3):
                await request_with_backoff(
                    client, "GET", "https://example.test/x", limiter=rl, sleep=clock.sleep
                )
        # Two of the three calls had to wait out the interval.
        assert len(clock.sleeps) == 2
