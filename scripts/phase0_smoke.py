#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Phase 0 smoke probe: does the Spotify surface crate depends on actually work?

Exercises every endpoint the MVP plan relies on against a live dev-mode Client ID,
plus the two no-auth fallback providers (ReccoBeats audio features, Deezer previews).
Each probe is independent — failures are recorded, never fatal — and results are
written into the RESULTS section of thoughts/shared/research/2026-07-phase0-spotify-smoke.md.
Successful response bodies are saved to thoughts/shared/research/phase0-fixtures/
for later use as contract-test fixtures.

Usage:
    # Full run (needs a Spotify dev app; opens a browser for OAuth consent):
    SPOTIFY_CLIENT_ID=<client id> uv run scripts/phase0_smoke.py

    # Reuse an existing scratch playlist for the write probes instead of creating one:
    SPOTIFY_CLIENT_ID=... SCRATCH_PLAYLIST_ID=<playlist id> uv run scripts/phase0_smoke.py

    # Only the probes that need no Spotify auth (ReccoBeats + Deezer):
    uv run scripts/phase0_smoke.py --no-auth-only

The Spotify app must have http://127.0.0.1:8200/auth/callback registered as a
redirect URI (loopback addresses are exempt from Spotify's HTTPS-only rule).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
FINDINGS_PATH = REPO_ROOT / "thoughts/shared/research/2026-07-phase0-spotify-smoke.md"
FIXTURES_DIR = REPO_ROOT / "thoughts/shared/research/phase0-fixtures"

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8200
CALLBACK_PATH = "/auth/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"

SPOTIFY_SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-library-read",
    "user-library-modify",
    "user-top-read",
    "user-read-recently-played",
    "user-read-currently-playing",
    "streaming",
]

SPOTIFY_API = "https://api.spotify.com/v1"

# Well-known tracks with their Spotify IDs, used for the ReccoBeats coverage probe
# (and a couple double as Spotify probe subjects). If ReccoBeats misses some of
# these mainstream tracks, coverage of a personal library will be worse — that
# hit rate is exactly the datum Phase 3 needs.
FAMOUS_TRACKS: list[tuple[str, str]] = [
    ("The Weeknd — Blinding Lights", "0VjIjW4GlUZAMYd2vXMi3b"),
    ("The Killers — Mr. Brightside", "003vvx7Niy0yvhvHt4a68B"),
    ("Ed Sheeran — Shape of You", "7qiZfU4dY1lWllzX7mPBI3"),
    ("Queen — Bohemian Rhapsody", "4u7EnebtmKWzUH433cf5Qv"),
    ("Nirvana — Smells Like Teen Spirit", "5ghIJDpPoe3CfHMGu71E6T"),
    ("Michael Jackson — Billie Jean", "5ChkMS8OtdzJeqyybCc9R5"),
    ("Eagles — Hotel California", "40riOy7x9W7GXjyGp4pjAv"),
    ("Daft Punk — Get Lucky", "2Foc5Q5nqNiosCNqttzHof"),
    ("Mark Ronson — Uptown Funk", "32OlwWuMpZ6b0aN2RZOeMS"),
    ("Tones and I — Dance Monkey", "2XU0oxnq2qxCpomAAuJY8K"),
    ("Lewis Capaldi — Someone You Loved", "7qEHsqek33rTcFNT9PFqLf"),
    ("Lady Gaga & Bradley Cooper — Shallow", "2VxeLyX666F8uXCJ0dZF8B"),
    ("Luis Fonsi — Despacito", "6habFhsOp2NvshLv26DqMb"),
    ("Billie Eilish — bad guy", "2Fxmhks0bxGSBdJ92vM42m"),
    ("Drake — One Dance", "1zi7xx7UVEFkmKfv06H8x0"),
    ("The Chainsmokers — Closer", "7BKLCZ1jbUBVqRi2FVlTVw"),
    ("Guns N' Roses — Sweet Child O' Mine", "7o2CTH4ctstm8TNelqjb51"),
    ("Dua Lipa — Levitating", "39LLxExYz6ewLAcYrzQQyP"),
    ("Led Zeppelin — Stairway to Heaven", "5CQ30WqJwcep0pYcV4AMNc"),
    ("a-ha — Take On Me", "2WfaOiMkCvy7F5fcp2zZ8L"),
    ("Harry Styles — Watermelon Sugar", "6UelLqGlWMcVH1E5c4H7lY"),
    ("The Weeknd — Starboy", "7MXVkk9YMctZqd1Srtv4MB"),
]

# Queries for the Deezer preview probe: search each, then HEAD the preview URL.
DEEZER_QUERIES = [
    "Blinding Lights The Weeknd",
    "Mr Brightside The Killers",
    "Bohemian Rhapsody Queen",
    "bad guy Billie Eilish",
    "Get Lucky Daft Punk",
]

POLITE_DELAY_S = 0.5  # pause between calls to unauthenticated public APIs


@dataclass
class ProbeResult:
    name: str
    verdict: str  # "PASS" / "FAIL" / "WARN" / "SKIP"
    status: str = "-"  # HTTP status or short state
    latency_ms: str = "-"
    notes: str = ""


@dataclass
class Runner:
    spotify_results: list[ProbeResult] = field(default_factory=list)
    noauth_results: list[ProbeResult] = field(default_factory=list)


def save_fixture(name: str, payload: object) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURES_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2))


def timed(client: httpx.Client, method: str, url: str, **kwargs) -> tuple[httpx.Response, int]:
    start = time.monotonic()
    resp = client.request(method, url, **kwargs)
    return resp, int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# No-auth probes: ReccoBeats + Deezer
# ---------------------------------------------------------------------------


def probe_reccobeats(results: list[ProbeResult]) -> None:
    ids = [track_id for _, track_id in FAMOUS_TRACKS]
    with httpx.Client(timeout=30) as client:
        try:
            resp, ms = timed(
                client,
                "GET",
                "https://api.reccobeats.com/v1/audio-features",
                params={"ids": ",".join(ids)},
            )
        except httpx.HTTPError as exc:
            results.append(ProbeResult("ReccoBeats audio-features", "FAIL", "error", notes=str(exc)))
            return

        if resp.status_code != 200:
            results.append(
                ProbeResult(
                    "ReccoBeats audio-features",
                    "FAIL",
                    str(resp.status_code),
                    str(ms),
                    notes=resp.text[:200],
                )
            )
            return

        body = resp.json()
        save_fixture("reccobeats_audio_features", body)
        items = body.get("content", body if isinstance(body, list) else [])

        # ReccoBeats items reference the source Spotify track via an
        # open.spotify.com href; match those back to the requested IDs.
        returned_ids: set[str] = set()
        for item in items:
            href = item.get("href", "") if isinstance(item, dict) else ""
            match = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]+)", href)
            if match:
                returned_ids.add(match.group(1))

        hits = [(label, tid) for label, tid in FAMOUS_TRACKS if tid in returned_ids]
        misses = [(label, tid) for label, tid in FAMOUS_TRACKS if tid not in returned_ids]
        matchable = bool(returned_ids)
        hit_rate = f"{len(hits)}/{len(ids)}" if matchable else f"{len(items)}/{len(ids)} (unmatched)"

        sample = items[0] if items else {}
        feature_keys = sorted(sample.keys()) if isinstance(sample, dict) else []
        notes = f"hit rate {hit_rate}; feature keys: {', '.join(feature_keys)}"
        if misses and matchable:
            notes += "; missing: " + "; ".join(label for label, _ in misses)

        verdict = "PASS" if len(items) >= len(ids) * 0.8 else ("WARN" if items else "FAIL")
        results.append(ProbeResult("ReccoBeats audio-features", verdict, "200", str(ms), notes))


def probe_deezer(results: list[ProbeResult]) -> None:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        reachable = 0
        details: list[str] = []
        first_fixture_saved = False
        for query in DEEZER_QUERIES:
            time.sleep(POLITE_DELAY_S)
            try:
                resp, ms = timed(
                    client, "GET", "https://api.deezer.com/search", params={"q": query}
                )
                data = resp.json().get("data", [])
            except (httpx.HTTPError, ValueError) as exc:
                details.append(f"{query}: search error ({exc})")
                continue

            if resp.status_code != 200 or not data:
                details.append(f"{query}: no results (HTTP {resp.status_code})")
                continue

            if not first_fixture_saved:
                save_fixture("deezer_search_sample", resp.json())
                first_fixture_saved = True

            preview_url = data[0].get("preview")
            if not preview_url:
                details.append(f"{query}: result has no preview URL")
                continue

            time.sleep(POLITE_DELAY_S)
            try:
                head, head_ms = timed(client, "HEAD", preview_url)
                # Some CDNs reject HEAD; a ranged GET is the honest fallback.
                if head.status_code != 200:
                    head, head_ms = timed(
                        client, "GET", preview_url, headers={"Range": "bytes=0-1023"}
                    )
            except httpx.HTTPError as exc:
                details.append(f"{query}: preview fetch error ({exc})")
                continue

            ctype = head.headers.get("content-type", "?")
            clen = head.headers.get("content-length", "?")
            if head.status_code in (200, 206):
                reachable += 1
                details.append(f"{query}: OK {head.status_code} {ctype} {clen}B {head_ms}ms")
            else:
                details.append(f"{query}: preview HTTP {head.status_code}")

        verdict = "PASS" if reachable == len(DEEZER_QUERIES) else ("WARN" if reachable else "FAIL")
        results.append(
            ProbeResult(
                "Deezer search + 30s preview",
                verdict,
                "200",
                "-",
                f"{reachable}/{len(DEEZER_QUERIES)} previews reachable. " + " | ".join(details),
            )
        )


# ---------------------------------------------------------------------------
# Spotify OAuth (Authorization Code + PKCE, loopback callback server)
# ---------------------------------------------------------------------------


def obtain_spotify_token(client_id: str) -> str:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(16)

    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(SPOTIFY_SCOPES),
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
    )

    captured: dict[str, str] = {}
    done = threading.Event()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            params = dict(urllib.parse.parse_qsl(parsed.query))
            captured.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>crate phase 0: auth received, return to the terminal.</h1>")
            done.set()

        def log_message(self, *args) -> None:  # silence per-request stderr noise
            pass

    server = http.server.HTTPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"Opening browser for Spotify consent…\nIf it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    if not done.wait(timeout=300):
        server.shutdown()
        raise TimeoutError("No OAuth callback received within 5 minutes")
    server.shutdown()

    if captured.get("state") != state:
        raise RuntimeError("OAuth state mismatch — aborting")
    if "error" in captured:
        raise RuntimeError(f"OAuth error: {captured['error']}")

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": captured["code"],
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    print("Access token obtained.\n")
    return token


# ---------------------------------------------------------------------------
# Spotify probes — each independent; failures recorded, not fatal
# ---------------------------------------------------------------------------


def run_spotify_probes(token: str, results: list[ProbeResult]) -> None:
    client = httpx.Client(
        base_url=SPOTIFY_API, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    pause = lambda: time.sleep(0.2)  # noqa: E731 — light throttle between authed calls

    def record(name: str, resp: httpx.Response, ms: int, ok_notes: str = "") -> bool:
        ok = 200 <= resp.status_code < 300
        results.append(
            ProbeResult(
                name,
                "PASS" if ok else "FAIL",
                str(resp.status_code),
                str(ms),
                ok_notes if ok else resp.text[:200],
            )
        )
        return ok

    def failed(name: str, exc: Exception) -> None:
        results.append(ProbeResult(name, "FAIL", "error", notes=str(exc)))

    # --- who am I (needed for playlist create) ---
    user_id = None
    try:
        resp, ms = timed(client, "GET", "/me")
        if record("GET /me (profile)", resp, ms):
            user_id = resp.json()["id"]
            save_fixture("spotify_me", resp.json())
    except Exception as exc:
        failed("GET /me (profile)", exc)

    # --- playlists read ---
    playlists: list[dict] = []
    pause()
    try:
        resp, ms = timed(client, "GET", "/me/playlists", params={"limit": 50})
        if record(
            "GET /me/playlists",
            resp,
            ms,
            f"{resp.json().get('total', '?')} playlists, snapshot_id present: "
            f"{all('snapshot_id' in p for p in resp.json().get('items', []))}",
        ):
            playlists = resp.json().get("items", [])
            save_fixture("spotify_me_playlists", resp.json())
    except Exception as exc:
        failed("GET /me/playlists", exc)

    # --- playlist tracks (snapshot_id + ISRC presence rate) ---
    artist_ids: list[str] = []
    pause()
    try:
        if not playlists:
            results.append(
                ProbeResult("GET /playlists/{id}/tracks", "SKIP", notes="no playlists to sample")
            )
        else:
            target = playlists[0]
            resp, ms = timed(
                client, "GET", f"/playlists/{target['id']}/tracks", params={"limit": 100}
            )
            if 200 <= resp.status_code < 300:
                items = resp.json().get("items", [])
                tracks = [i["track"] for i in items if i.get("track")]
                with_isrc = sum(
                    1 for t in tracks if t.get("external_ids", {}).get("isrc")
                )
                isrc_rate = f"{with_isrc}/{len(tracks)}" if tracks else "0/0"
                for t in tracks:
                    for a in t.get("artists", []):
                        if a.get("id") and a["id"] not in artist_ids:
                            artist_ids.append(a["id"])
                save_fixture("spotify_playlist_tracks", resp.json())
                record(
                    "GET /playlists/{id}/tracks",
                    resp,
                    ms,
                    f"playlist '{target['name']}', ISRC present {isrc_rate}, "
                    f"snapshot_id on playlist: {bool(target.get('snapshot_id'))}",
                )
            else:
                record("GET /playlists/{id}/tracks", resp, ms)
    except Exception as exc:
        failed("GET /playlists/{id}/tracks", exc)

    # --- playlist create (also provides the scratch playlist if none given) ---
    scratch_id = os.environ.get("SCRATCH_PLAYLIST_ID")
    pause()
    try:
        if user_id is None:
            results.append(
                ProbeResult("POST /users/{id}/playlists (create)", "SKIP", notes="/me failed")
            )
        else:
            resp, ms = timed(
                client,
                "POST",
                f"/users/{user_id}/playlists",
                json={
                    "name": f"crate phase0 scratch {time.strftime('%Y-%m-%d %H:%M')}",
                    "public": False,
                    "description": "throwaway playlist created by crate's phase 0 smoke probe — safe to delete",
                },
            )
            if record("POST /users/{id}/playlists (create)", resp, ms, "created private playlist"):
                save_fixture("spotify_playlist_create", resp.json())
                if not scratch_id:
                    scratch_id = resp.json()["id"]
    except Exception as exc:
        failed("POST /users/{id}/playlists (create)", exc)

    # --- playlist write: add then remove a track on the scratch playlist ---
    test_uri = f"spotify:track:{FAMOUS_TRACKS[0][1]}"  # Blinding Lights
    pause()
    try:
        if not scratch_id:
            results.append(
                ProbeResult(
                    "POST /playlists/{id}/tracks (add)",
                    "SKIP",
                    notes="no scratch playlist (set SCRATCH_PLAYLIST_ID or fix create)",
                )
            )
        else:
            resp, ms = timed(
                client, "POST", f"/playlists/{scratch_id}/tracks", json={"uris": [test_uri]}
            )
            record(
                "POST /playlists/{id}/tracks (add)",
                resp,
                ms,
                f"snapshot_id returned: {'snapshot_id' in resp.json() if resp.status_code < 300 else '-'}",
            )
    except Exception as exc:
        failed("POST /playlists/{id}/tracks (add)", exc)

    pause()
    try:
        if not scratch_id:
            results.append(
                ProbeResult("DELETE /playlists/{id}/tracks (remove)", "SKIP", notes="no scratch playlist")
            )
        else:
            resp, ms = timed(
                client,
                "DELETE",
                f"/playlists/{scratch_id}/tracks",
                json={"tracks": [{"uri": test_uri}]},
            )
            record(
                "DELETE /playlists/{id}/tracks (remove)",
                resp,
                ms,
                f"snapshot_id returned: {'snapshot_id' in resp.json() if resp.status_code < 300 else '-'}",
            )
    except Exception as exc:
        failed("DELETE /playlists/{id}/tracks (remove)", exc)

    # --- saved tracks ---
    pause()
    try:
        resp, ms = timed(client, "GET", "/me/tracks", params={"limit": 20})
        if record("GET /me/tracks (saved)", resp, ms, f"total: {resp.json().get('total', '?')}"):
            save_fixture("spotify_me_tracks", resp.json())
    except Exception as exc:
        failed("GET /me/tracks (saved)", exc)

    # --- search ---
    pause()
    try:
        resp, ms = timed(
            client,
            "GET",
            "/search",
            params={"q": "track:Blinding Lights artist:The Weeknd", "type": "track", "limit": 5},
        )
        if record(
            "GET /search",
            resp,
            ms,
            f"{len(resp.json().get('tracks', {}).get('items', []))} results",
        ):
            save_fixture("spotify_search", resp.json())
    except Exception as exc:
        failed("GET /search", exc)

    # --- top tracks ---
    pause()
    try:
        resp, ms = timed(client, "GET", "/me/top/tracks", params={"limit": 20})
        if record("GET /me/top/tracks", resp, ms, f"{len(resp.json().get('items', []))} items"):
            save_fixture("spotify_top_tracks", resp.json())
            for t in resp.json().get("items", []):
                for a in t.get("artists", []):
                    if a.get("id") and a["id"] not in artist_ids:
                        artist_ids.append(a["id"])
    except Exception as exc:
        failed("GET /me/top/tracks", exc)

    # --- recently played ---
    pause()
    try:
        resp, ms = timed(client, "GET", "/me/player/recently-played", params={"limit": 20})
        if record(
            "GET /me/player/recently-played", resp, ms, f"{len(resp.json().get('items', []))} items"
        ):
            save_fixture("spotify_recently_played", resp.json())
    except Exception as exc:
        failed("GET /me/player/recently-played", exc)

    # --- single track ---
    pause()
    try:
        resp, ms = timed(client, "GET", f"/tracks/{FAMOUS_TRACKS[0][1]}")
        if record(
            "GET /tracks/{id}",
            resp,
            ms,
            f"isrc: {resp.json().get('external_ids', {}).get('isrc', 'MISSING')}, "
            f"preview_url: {resp.json().get('preview_url')}",
        ):
            save_fixture("spotify_track_single", resp.json())
    except Exception as exc:
        failed("GET /tracks/{id}", exc)

    # --- artist genres emptiness over ~50 artists ---
    pause()
    try:
        sample = artist_ids[:50]
        if not sample:
            results.append(
                ProbeResult(
                    "GET /artists?ids= (genres survey)", "SKIP", notes="no artist ids gathered"
                )
            )
        else:
            resp, ms = timed(client, "GET", "/artists", params={"ids": ",".join(sample)})
            if 200 <= resp.status_code < 300:
                artists = resp.json().get("artists", [])
                empty = sum(1 for a in artists if a and not a.get("genres"))
                save_fixture("spotify_artists_batch", resp.json())
                record(
                    "GET /artists?ids= (genres survey)",
                    resp,
                    ms,
                    f"{empty}/{len(artists)} artists have EMPTY genres "
                    f"({empty / len(artists) * 100:.0f}% empty)",
                )
            else:
                record("GET /artists?ids= (genres survey)", resp, ms)
    except Exception as exc:
        failed("GET /artists?ids= (genres survey)", exc)

    client.close()


# ---------------------------------------------------------------------------
# Findings doc update: replace only this run's marker block, keep everything else
# ---------------------------------------------------------------------------


def render_table(results: list[ProbeResult]) -> str:
    lines = [
        "| Probe | Verdict | HTTP | Latency (ms) | Notes |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        notes = r.notes.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r.name} | {r.verdict} | {r.status} | {r.latency_ms} | {notes} |")
    return "\n".join(lines)


def update_findings(section: str, table: str) -> None:
    begin, end = f"<!-- {section}:BEGIN -->", f"<!-- {section}:END -->"
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    block = f"{begin}\n_Last run: {stamp}_\n\n{table}\n{end}"

    if FINDINGS_PATH.exists():
        text = FINDINGS_PATH.read_text()
        if begin in text and end in text:
            pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
            text = pattern.sub(block, text)
        else:
            text = text.rstrip() + f"\n\n{block}\n"
    else:
        text = f"# Phase 0 smoke results\n\n{block}\n"
    FINDINGS_PATH.write_text(text)
    print(f"Wrote {section} block to {FINDINGS_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-auth-only",
        action="store_true",
        help="run only the ReccoBeats/Deezer probes (no Spotify auth needed)",
    )
    args = parser.parse_args()

    runner = Runner()

    print("== No-auth probes: ReccoBeats + Deezer ==")
    probe_reccobeats(runner.noauth_results)
    time.sleep(POLITE_DELAY_S)
    probe_deezer(runner.noauth_results)
    update_findings("NOAUTH-RESULTS", render_table(runner.noauth_results))

    if not args.no_auth_only:
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        if not client_id:
            print("ERROR: SPOTIFY_CLIENT_ID env var is required for the Spotify probes.")
            print("Re-run with --no-auth-only to skip them.")
            return 1
        print("\n== Spotify probes ==")
        token = obtain_spotify_token(client_id)
        run_spotify_probes(token, runner.spotify_results)
        update_findings("SPOTIFY-RESULTS", render_table(runner.spotify_results))

    print("\n== Summary ==")
    for r in runner.noauth_results + runner.spotify_results:
        print(f"  [{r.verdict:4}] {r.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
