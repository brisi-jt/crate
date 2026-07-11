"""Spotify client unit tests — fully offline via httpx.MockTransport."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from crate.model.enums import ReauthReason
from crate.services.spotify.auth import (
    build_authorize_url,
    code_challenge,
    exchange_code,
    generate_code_verifier,
)
from crate.services.spotify.client import (
    ACCOUNTS_TOKEN_URL,
    SpotifyApiError,
    SpotifyClient,
    SpotifyReauthRequired,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "spotify"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_client(handler, **kwargs) -> SpotifyClient:
    return SpotifyClient(
        client_id="test-client-id",
        access_token=kwargs.pop("access_token", "initial-access-token"),
        refresh_token=kwargs.pop("refresh_token", "initial-refresh-token"),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_iter_playlists_follows_pagination() -> None:
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        if "offset=2" in str(request.url):
            return httpx.Response(200, json=fixture("me_playlists_page2.json"))
        return httpx.Response(200, json=fixture("me_playlists_page1.json"))

    client = make_client(handler)
    playlists = [p async for p in client.iter_playlists()]
    await client.aclose()

    assert [p.id for p in playlists] == [
        "3cEYpjA9oz9GiPac4AsH4n",
        "1AVZz0mBuGbCEoNRQdYQju",
        "5W1cKzKqdzEjHeSbHrGNUf",
    ]
    assert playlists[0].snapshot_id.startswith("MTgs")
    assert playlists[0].owner is not None and playlists[0].owner.id == "spotify-jt"
    assert playlists[2].owner is not None and playlists[2].owner.id == "other-user"
    assert all(auth == "Bearer initial-access-token" for auth in seen_auth)
    assert len(seen_auth) == 2


async def test_iter_playlist_tracks_parses_isrc_and_artists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "offset=2" in str(request.url):
            return httpx.Response(200, json=fixture("playlist_tracks_page2.json"))
        return httpx.Response(200, json=fixture("playlist_tracks_page1.json"))

    client = make_client(handler)
    items = [t async for t in client.iter_playlist_tracks("3cEYpjA9oz9GiPac4AsH4n")]
    await client.aclose()

    assert len(items) == 3
    first = items[0].track
    assert first is not None
    assert first.id == "6UelLqGlWMcVH1E5c4H7lY"
    assert first.external_ids.isrc == "GBAYE1900123"
    second = items[1].track
    assert second is not None
    assert [a.name for a in second.artists] == ["Signal Artist", "Feature Artist"]
    assert items[0].added_at is not None


async def test_429_honors_retry_after() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json=fixture("me.json"))

    sleeper = SleepRecorder()
    client = make_client(handler, sleep=sleeper)
    profile = await client.get_current_user()
    await client.aclose()

    assert profile.id == "spotify-jt"
    assert sleeper.calls == [3.0]
    assert attempts["n"] == 2


async def test_401_refreshes_token_and_retries() -> None:
    refreshed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ACCOUNTS_TOKEN_URL:
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["initial-refresh-token"]
            assert form["client_id"] == ["test-client-id"]
            return httpx.Response(200, json=fixture("token_response.json"))
        if request.headers.get("Authorization") == "Bearer initial-access-token":
            return httpx.Response(401, json={"error": {"status": 401, "message": "expired"}})
        return httpx.Response(200, json=fixture("me.json"))

    client = make_client(handler, on_tokens=refreshed.append)
    profile = await client.get_current_user()
    await client.aclose()

    assert profile.id == "spotify-jt"
    # The persist hook receives the new refresh token so callers can re-encrypt it.
    assert refreshed and "syntheticrefreshtoken" in refreshed[0]


async def test_refresh_failure_raises_reauth_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ACCOUNTS_TOKEN_URL:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(401, json={"error": {"status": 401}})

    client = make_client(handler)
    with pytest.raises(SpotifyReauthRequired):
        await client.get_current_user()
    await client.aclose()


# --- refresh-token expiry (invalid_grant, 6-month TTL) ------------------------


async def test_refresh_invalid_grant_is_token_expired_and_not_retried() -> None:
    """An expired refresh token comes back as 400 invalid_grant; the client
    must classify it as token_expired and never re-attempt the refresh."""
    token_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ACCOUNTS_TOKEN_URL:
            token_calls["n"] += 1
            return httpx.Response(400, json=fixture("token_refresh_invalid_grant.json"))
        return httpx.Response(401, json={"error": {"status": 401, "message": "expired"}})

    client = make_client(handler, access_token=None)
    with pytest.raises(SpotifyReauthRequired) as exc_info:
        await client.get_current_user()
    await client.aclose()

    assert exc_info.value.reason == ReauthReason.token_expired
    assert token_calls["n"] == 1


async def test_refresh_other_400_is_generic_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ACCOUNTS_TOKEN_URL:
            return httpx.Response(400, json={"error": "invalid_request"})
        return httpx.Response(401, json={"error": {"status": 401}})

    client = make_client(handler, access_token=None)
    with pytest.raises(SpotifyReauthRequired) as exc_info:
        await client.get_current_user()
    await client.aclose()

    assert exc_info.value.reason == ReauthReason.refresh_rejected


async def test_refresh_non_json_400_is_generic_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ACCOUNTS_TOKEN_URL:
            return httpx.Response(400, text="Bad Request")
        return httpx.Response(401, json={"error": {"status": 401}})

    client = make_client(handler, access_token=None)
    with pytest.raises(SpotifyReauthRequired) as exc_info:
        await client.get_current_user()
    await client.aclose()

    assert exc_info.value.reason == ReauthReason.refresh_rejected


# --- /items migration (playlist endpoint renames) ------------------------------


async def test_iter_playlist_tracks_uses_items_path_by_default() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if "offset=2" in str(request.url):
            return httpx.Response(200, json=fixture("playlist_items_page2.json"))
        return httpx.Response(200, json=fixture("playlist_items_page1.json"))

    client = make_client(handler)
    items = [t async for t in client.iter_playlist_tracks("3cEYpjA9oz9GiPac4AsH4n")]
    await client.aclose()

    assert paths[0] == "/v1/playlists/3cEYpjA9oz9GiPac4AsH4n/items"
    assert len(items) == 3
    first = items[0].track
    assert first is not None
    assert first.id == "6UelLqGlWMcVH1E5c4H7lY"
    assert first.external_ids.isrc == "GBAYE1900123"


async def test_iter_playlist_tracks_falls_back_to_tracks_on_403() -> None:
    """Followed-but-unowned playlists 403 on /items; the deprecated /tracks
    path still serves them, so full-library sync keeps working."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/items"):
            return httpx.Response(403, json={"error": {"status": 403, "message": "Forbidden"}})
        if "offset=2" in str(request.url):
            return httpx.Response(200, json=fixture("playlist_tracks_page2.json"))
        return httpx.Response(200, json=fixture("playlist_tracks_page1.json"))

    client = make_client(handler)
    items = [t async for t in client.iter_playlist_tracks("3cEYpjA9oz9GiPac4AsH4n")]
    await client.aclose()

    assert paths[:2] == [
        "/v1/playlists/3cEYpjA9oz9GiPac4AsH4n/items",
        "/v1/playlists/3cEYpjA9oz9GiPac4AsH4n/tracks",
    ]
    assert len(items) == 3


async def test_flag_off_uses_tracks_path_with_items_fallback() -> None:
    """With the feature flag off, /tracks is primary — and a hard-cut
    (404/410) falls forward to /items instead of stranding the sync."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/tracks"):
            return httpx.Response(410, json={"error": {"status": 410, "message": "Gone"}})
        if "offset=2" in str(request.url):
            return httpx.Response(200, json=fixture("playlist_items_page2.json"))
        return httpx.Response(200, json=fixture("playlist_items_page1.json"))

    client = make_client(handler, use_items_endpoints=False)
    items = [t async for t in client.iter_playlist_tracks("3cEYpjA9oz9GiPac4AsH4n")]
    await client.aclose()

    assert paths[:2] == [
        "/v1/playlists/3cEYpjA9oz9GiPac4AsH4n/tracks",
        "/v1/playlists/3cEYpjA9oz9GiPac4AsH4n/items",
    ]
    assert len(items) == 3


def test_playlist_item_prefers_item_over_deprecated_track() -> None:
    """/items entries carry `item`, with `track` kept as a deprecated alias."""
    from crate.services.spotify.models import PlaylistTrackItem

    entry = PlaylistTrackItem.model_validate(
        {
            "added_at": "2026-01-01T00:00:00Z",
            "item": {"id": "current-id", "name": "Current"},
            "track": {"id": "deprecated-id", "name": "Deprecated"},
        }
    )
    assert entry.track is not None
    assert entry.track.id == "current-id"


def test_playlist_item_parses_item_only_entry() -> None:
    from crate.services.spotify.models import PlaylistTrackItem

    entry = PlaylistTrackItem.model_validate(
        {"added_at": None, "item": {"id": "only-item", "name": "Only"}}
    )
    assert entry.track is not None
    assert entry.track.id == "only-item"


def test_playlist_summary_reads_items_total() -> None:
    """The /items reshape reframes the summary's tracks.total as items.total."""
    from crate.services.spotify.models import SpotifyPlaylistSummary

    summary = SpotifyPlaylistSummary.model_validate(
        {
            "id": "pl1",
            "name": "reshaped",
            "snapshot_id": "snap",
            "items": {"total": 7},
        }
    )
    assert summary.tracks.total == 7


async def test_server_error_raises_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"status": 500, "message": "oops"}})

    client = make_client(handler)
    with pytest.raises(SpotifyApiError):
        await client.get_current_user()
    await client.aclose()


# --- PKCE helpers -----------------------------------------------------------


def test_code_challenge_matches_rfc7636_vector() -> None:
    # Appendix B of RFC 7636.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_generate_code_verifier_charset_and_length() -> None:
    verifier = generate_code_verifier()
    assert 43 <= len(verifier) <= 128
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert set(verifier) <= allowed
    assert verifier != generate_code_verifier()


def test_build_authorize_url_params() -> None:
    url = build_authorize_url(
        client_id="test-client-id",
        redirect_uri="http://127.0.0.1:8200/v1/auth/spotify/callback",
        state="abc123",
        challenge="challenge-value",
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.hostname == "accounts.spotify.com"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["test-client-id"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == ["challenge-value"]
    assert params["state"] == ["abc123"]
    assert "playlist-read-private" in params["scope"][0]


async def test_exchange_code_posts_pkce_form() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ACCOUNTS_TOKEN_URL
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["auth-code-1"]
        assert form["code_verifier"] == ["verifier-1"]
        assert form["redirect_uri"] == ["http://127.0.0.1:8200/v1/auth/spotify/callback"]
        return httpx.Response(200, json=fixture("token_response.json"))

    tokens = await exchange_code(
        client_id="test-client-id",
        code="auth-code-1",
        redirect_uri="http://127.0.0.1:8200/v1/auth/spotify/callback",
        code_verifier="verifier-1",
        transport=httpx.MockTransport(handler),
    )
    assert tokens.access_token.startswith("BQD")
    assert tokens.refresh_token is not None
    assert tokens.expires_in == 3600


async def test_search_tracks_parses_items() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=fixture("search_tracks.json"))

    client = make_client(handler)
    tracks = await client.search_tracks('track:"Dayvan Cowboy" artist:"Boards of Canada"')
    await client.aclose()

    assert [t.id for t in tracks] == ["2CvOqDpQIMw69cCzWqr5yr", "7x8dCjCr0x6x2lXKujYD34"]
    assert tracks[0].external_ids.isrc == "GBAFL0500202"
    assert tracks[0].artists[0].name == "Boards of Canada"
    params = requests[0].url.params
    assert params["type"] == "track"
    assert params["limit"] == "5"
    assert params["q"] == 'track:"Dayvan Cowboy" artist:"Boards of Canada"'


async def test_search_tracks_clamps_limit_to_dev_mode_cap() -> None:
    """Dev-mode search caps limit at 10 — callers passing more get clamped."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=fixture("search_tracks.json"))

    client = make_client(handler)
    await client.search_tracks("isrc:GBAFL0500202", limit=25)
    await client.aclose()

    assert requests[0].url.params["limit"] == "10"


async def test_search_tracks_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tracks": {"items": [], "total": 0}})

    client = make_client(handler)
    assert await client.search_tracks("isrc:ZZZ00000000") == []
    await client.aclose()


def test_playlist_item_parses_local_file_with_null_artist_fields() -> None:
    """Local files come back with null artist id AND name; parsing must not raise.

    Observed live on 2026-07-11 (first real-library sync): a playlist holding a
    local file crashed the whole sync at validation time, before the sync
    engine's local/ghost skip could run.
    """
    from crate.services.spotify.models import PlaylistTrackItem

    item = PlaylistTrackItem.model_validate(
        {
            "added_at": "2020-05-01T10:00:00Z",
            "track": {
                "id": None,
                "name": "bootleg rip.mp3",
                "duration_ms": 183000,
                "is_local": True,
                "external_ids": {},
                "artists": [{"id": None, "name": None}],
                "album": {"id": None, "name": None},
            },
        }
    )
    assert item.track is not None
    assert item.track.is_local is True
    assert item.track.id is None  # the sync engine's skip condition


def test_playlist_item_parses_catalog_ghost() -> None:
    """Items whose track was removed from the catalog arrive as track: null."""
    from crate.services.spotify.models import PlaylistTrackItem

    item = PlaylistTrackItem.model_validate({"added_at": None, "track": None})
    assert item.track is None
