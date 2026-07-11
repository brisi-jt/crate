"""Spotify client account-data reads — offline via httpx.MockTransport."""

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from crate.services.spotify.client import SpotifyClient

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "spotify"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def make_client(handler) -> SpotifyClient:
    return SpotifyClient(
        client_id="test-client-id",
        access_token="initial-access-token",
        refresh_token="initial-refresh-token",
        transport=httpx.MockTransport(handler),
    )


async def test_iter_saved_tracks_follows_pages() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.params.get("offset") == "2":
            return httpx.Response(200, json=fixture("saved_tracks_page2.json"))
        return httpx.Response(200, json=fixture("saved_tracks_page1.json"))

    client = make_client(handler)
    items = [item async for item in client.iter_saved_tracks()]
    await client.aclose()

    assert len(items) == 3
    assert requests[0].startswith("https://api.spotify.com/v1/me/tracks")
    assert "limit=50" in requests[0]
    assert items[0].track.id == "3n3Ppam7vgaVa1iaRUc9Lp"
    assert items[0].added_at == datetime.fromisoformat("2026-07-01T10:00:00+00:00")
    assert items[0].track.external_ids.isrc == "USWB11300423"


async def test_get_recently_played_parses_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/me/player/recently-played"
        assert request.url.params.get("limit") == "50"
        return httpx.Response(200, json=fixture("recently_played.json"))

    client = make_client(handler)
    items = await client.get_recently_played()
    await client.aclose()

    assert len(items) == 2
    first, second = items
    assert first.track.id == "3n3Ppam7vgaVa1iaRUc9Lp"
    assert first.played_at == datetime.fromisoformat("2026-07-12T09:14:32.123000+00:00")
    assert first.context is not None
    assert first.context.type == "playlist"
    assert first.context.uri == "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    assert second.context is None


async def test_get_top_artists_and_tracks() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(f"{request.url.path}?{request.url.query.decode()}")
        if "/top/artists" in request.url.path:
            return httpx.Response(200, json=fixture("top_artists.json"))
        return httpx.Response(200, json=fixture("top_tracks.json"))

    client = make_client(handler)
    artists = await client.get_top_artists(time_range="short_term")
    tracks = await client.get_top_tracks(time_range="long_term", limit=10)
    await client.aclose()

    assert paths[0] == "/v1/me/top/artists?time_range=short_term&limit=50"
    assert paths[1] == "/v1/me/top/tracks?time_range=long_term&limit=10"
    assert [artist.name for artist in artists] == ["Boards of Canada", "Bonobo"]
    assert artists[0].id == "2VAvhf61GgLYmC6C8anyX1"
    assert tracks[0].id == "3n3Ppam7vgaVa1iaRUc9Lp"
    assert tracks[0].artists[0].name == "Boards of Canada"
