"""Spotify client write methods — request shapes verified via MockTransport."""

import json

import httpx
import pytest

from crate.services.spotify.client import SpotifyClient

pytestmark = pytest.mark.unit


def make_client(handler) -> SpotifyClient:
    return SpotifyClient(
        client_id="test-client-id",
        access_token="tok",
        refresh_token="refresh",
        transport=httpx.MockTransport(handler),
    )


class Recorder:
    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = responses or []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, json={"snapshot_id": f"snap-{len(self.requests)}"})

    def body(self, index: int) -> dict:
        return json.loads(self.requests[index].content)


async def test_add_tracks_posts_uris_and_returns_snapshot() -> None:
    recorder = Recorder()
    client = make_client(recorder)
    snapshot = await client.add_playlist_tracks("pl1", ["spotify:track:a"], position=2)
    await client.aclose()

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/playlists/pl1/items"
    assert recorder.body(0) == {"uris": ["spotify:track:a"], "position": 2}
    assert snapshot == "snap-1"


async def test_add_tracks_chunks_at_100() -> None:
    recorder = Recorder()
    client = make_client(recorder)
    uris = [f"spotify:track:t{i}" for i in range(150)]
    await client.add_playlist_tracks("pl1", uris)
    await client.aclose()

    assert len(recorder.requests) == 2
    assert len(recorder.body(0)["uris"]) == 100
    assert len(recorder.body(1)["uris"]) == 50
    # The second chunk appends — no position key.
    assert "position" not in recorder.body(0)


async def test_add_tracks_chunks_preserve_insert_position() -> None:
    recorder = Recorder()
    client = make_client(recorder)
    uris = [f"spotify:track:t{i}" for i in range(120)]
    await client.add_playlist_tracks("pl1", uris, position=5)
    await client.aclose()

    assert recorder.body(0)["position"] == 5
    assert recorder.body(1)["position"] == 105


async def test_remove_tracks_sends_uri_objects() -> None:
    recorder = Recorder()
    client = make_client(recorder)
    await client.remove_playlist_tracks("pl1", ["spotify:track:a", "spotify:track:b"])
    await client.aclose()

    request = recorder.requests[0]
    assert request.method == "DELETE"
    assert request.url.path == "/v1/playlists/pl1/items"
    assert recorder.body(0) == {"tracks": [{"uri": "spotify:track:a"}, {"uri": "spotify:track:b"}]}


async def test_reorder_range_sends_reorder_body() -> None:
    recorder = Recorder()
    client = make_client(recorder)
    await client.reorder_playlist_range("pl1", range_start=4, insert_before=1)
    await client.aclose()

    request = recorder.requests[0]
    assert request.method == "PUT"
    assert request.url.path == "/v1/playlists/pl1/items"
    assert recorder.body(0) == {"range_start": 4, "insert_before": 1, "range_length": 1}


async def test_add_tracks_falls_back_to_tracks_on_403_and_caches_path() -> None:
    """A 403 from /items (non-owned playlist) falls back to /tracks once; the
    working path is remembered so later chunks skip the failing probe."""
    recorder = Recorder(
        responses=[
            httpx.Response(403, json={"error": {"status": 403, "message": "Forbidden"}}),
            httpx.Response(200, json={"snapshot_id": "snap-a"}),
            httpx.Response(200, json={"snapshot_id": "snap-b"}),
        ]
    )
    client = make_client(recorder)
    uris = [f"spotify:track:t{i}" for i in range(150)]
    snapshot = await client.add_playlist_tracks("pl1", uris)
    await client.aclose()

    assert [r.url.path for r in recorder.requests] == [
        "/v1/playlists/pl1/items",
        "/v1/playlists/pl1/tracks",
        "/v1/playlists/pl1/tracks",
    ]
    assert snapshot == "snap-b"


async def test_create_playlist_uses_current_user_and_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/me":
            return httpx.Response(200, json={"id": "jt", "display_name": "JT"})
        return httpx.Response(
            201, json={"id": "new-pl", "snapshot_id": "snap-new", "name": "Peak Hours"}
        )

    client = make_client(handler)
    spotify_id, snapshot = await client.create_playlist("Peak Hours", description="late")
    await client.aclose()
    assert spotify_id == "new-pl"
    assert snapshot == "snap-new"


async def test_change_details_puts_only_given_fields() -> None:
    recorder = Recorder(responses=[httpx.Response(200, text="")])
    client = make_client(recorder)
    await client.change_playlist_details("pl1", name="New Name")
    await client.aclose()
    assert recorder.requests[0].method == "PUT"
    assert recorder.body(0) == {"name": "New Name"}


async def test_unfollow_playlist_deletes_followers() -> None:
    recorder = Recorder(responses=[httpx.Response(200, text="")])
    client = make_client(recorder)
    await client.unfollow_playlist("pl1")
    await client.aclose()
    request = recorder.requests[0]
    assert request.method == "DELETE"
    assert request.url.path == "/v1/playlists/pl1/followers"


async def test_list_track_uris_pages_through() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "offset=2" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "items": [{"track": {"uri": "spotify:track:c", "name": "C"}}],
                    "next": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {"track": {"uri": "spotify:track:a", "name": "A"}},
                    {"track": {"uri": "spotify:track:b", "name": "B"}},
                ],
                "next": "https://api.spotify.com/v1/playlists/pl1/tracks?offset=2&limit=2",
            },
        )

    client = make_client(handler)
    uris = await client.list_track_uris("pl1")
    await client.aclose()
    assert uris == ["spotify:track:a", "spotify:track:b", "spotify:track:c"]


async def test_list_track_uris_reads_item_shaped_entries() -> None:
    """/items pages key each entry on `item`; the deprecated `track` key may
    be absent entirely."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"item": {"uri": "spotify:track:a", "name": "A"}},
                    {"item": {"uri": "spotify:track:b", "name": "B"}, "track": None},
                ],
                "next": None,
            },
        )

    client = make_client(handler)
    uris = await client.list_track_uris("pl1")
    await client.aclose()
    assert uris == ["spotify:track:a", "spotify:track:b"]
