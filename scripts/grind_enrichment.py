"""Drive enrichment to completion, one budgeted pass at a time.

Each ``POST /v1/enrichment/run`` now returns within its wall-clock budget
(default 240s, cap 600s), so the driver is a plain loop: fire a pass, read the
counts, fire the next, stop when a pass drains the backlog. This replaces the
old ``--max-time`` shell loop whose curl timed out while the server kept
grinding for an hour, then overlapped a second pass on top of the first.

Contract this loop relies on:

- A pass returns promptly (≤ its budget). No request blocks unbounded.
- ``budget_exhausted: true`` means "more work remains, come straight back".
- A pass that processed nothing (no tracks, no artists, no local fills) means
  the selected stage is drained — the loop stops.
- 409 ``ENRICHMENT_PASS_ACTIVE`` means another driver/pass is already running;
  the loop waits and retries rather than piling on.

Run it against the local API (default base URL http://localhost:8200):

    uv run python scripts/grind_enrichment.py
    uv run python scripts/grind_enrichment.py --stage all
    uv run python scripts/grind_enrichment.py --base-url http://localhost:8200

Stages: run ``--stage feature`` first (fills the map's blocker fast), then
``--stage identity`` for the 1 req/s MusicBrainz + Last.fm work, or ``--stage
all`` to walk both in one grind.
"""

import argparse
import time

import httpx

# The API's local port (see the repo runbook); override with --base-url.
DEFAULT_BASE_URL = "http://localhost:8200"


def pass_did_work(body: dict) -> bool:
    """True while the selected stage still has un-enriched rows to process.

    ``artists_identity_examined`` is the identity stage's key-independent
    progress signal: a pass that visits artists lacking an MBID but resolves
    none (their tracks carry no MusicBrainz-matchable ISRC) still did work and
    the next pass should run. Keying only off ``artists_mbid_resolved`` made
    the driver stop after one pass while thousands of artists still had no MBID.

    ``artists_genre_examined`` is the same signal for the genre-write pass: an
    MBID'd artist MusicBrainz has no genres for is still examined-and-marked, so
    the pass did work even when no ArtistGenre rows landed. Without it the
    driver would stop while MBID'd artists still had un-fetched genres.
    """
    return bool(
        body.get("tracks_processed", 0)
        or body.get("features_from_localdsp", 0)
        or body.get("artists_processed", 0)
        or body.get("artists_identity_examined", 0)
        or body.get("artists_mbid_resolved", 0)
        or body.get("artists_genre_examined", 0)
    )


def summarize(body: dict) -> str:
    parts = [
        f"tracks={body.get('tracks_processed', 0)}",
        f"recco={body.get('features_from_reccobeats', 0)}",
        f"isrc={body.get('features_from_isrc_fallback', 0)}",
        f"freqblog={body.get('features_from_freqblog', 0)}",
        f"localdsp={body.get('features_from_localdsp', 0)}",
        f"missing={body.get('features_missing', 0)}",
        f"artists={body.get('artists_identity_examined', 0)}",
        f"mbid={body.get('artists_mbid_resolved', 0)}",
        f"namembid={body.get('artists_mbid_from_name_search', 0)}",
        f"genreex={body.get('artists_genre_examined', 0)}",
        f"genrerows={body.get('artist_genre_rows_written', 0)}",
    ]
    if body.get("budget_exhausted"):
        parts.append("BUDGET_EXHAUSTED")
    stage_seconds = body.get("stage_seconds") or {}
    if stage_seconds:
        spent = ", ".join(f"{k}={v:.0f}s" for k, v in stage_seconds.items() if v)
        if spent:
            parts.append(f"[{spent}]")
    errors = body.get("errors") or []
    if errors:
        parts.append(f"errors={len(errors)}")
    return " ".join(parts)


def _recompute_on_drain(
    client: httpx.Client, recompute_url: str, genre_rows_written: int, args
) -> None:
    """Warm the clustering cache once the grind drains, if genres changed.

    Every genre-writing pass already invalidates the analytics snapshots, so a
    later read recomputes with the new coverage. This fires one recompute at the
    end so the improved clustering is warm before anyone opens the map — but only
    when this grind actually wrote genre rows, so a no-op drain stays a no-op.
    """
    if args.no_recompute_on_drain or genre_rows_written <= 0:
        return
    print(f"grind wrote {genre_rows_written} genre rows; recomputing analytics", flush=True)
    try:
        response = client.post(recompute_url)
    except httpx.RequestError as exc:
        print(f"recompute request failed: {exc!r} (invalidated snapshots recompute on next read)")
        return
    if response.status_code == 200:
        print("analytics recomputed; clustering reflects the new genre coverage", flush=True)
    else:
        print(f"recompute returned {response.status_code}: {response.text[:200]}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help=f"API base URL (default: {DEFAULT_BASE_URL})."
    )
    parser.add_argument(
        "--stage",
        choices=("feature", "identity", "all"),
        default="feature",
        help="Pipeline slice to grind (default: feature).",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per pass (default 500).")
    parser.add_argument(
        "--time-budget",
        type=int,
        default=240,
        help="Per-pass wall-clock budget in seconds (server caps at 600).",
    )
    parser.add_argument(
        "--active-wait",
        type=float,
        default=10.0,
        help="Seconds to wait before retrying after a 409 ENRICHMENT_PASS_ACTIVE.",
    )
    parser.add_argument(
        "--max-passes", type=int, default=0, help="Stop after N passes (0 = until drained)."
    )
    parser.add_argument(
        "--no-recompute-on-drain",
        action="store_true",
        help="Skip the one analytics recompute fired when the grind drains "
        "(the default warms the clustering cache so new genre coverage lands).",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    url = f"{base_url}/v1/enrichment/run"
    recompute_url = f"{base_url}/v1/analytics/recompute"
    params = {
        "stage": args.stage,
        "batch_size": args.batch_size,
        "time_budget_seconds": args.time_budget,
    }
    # No read timeout: a pass is server-bounded by its wall-clock budget, so the
    # client just waits for it to return (with headroom over the 600s cap).
    timeout = httpx.Timeout(connect=10.0, read=args.time_budget + 120, write=10.0, pool=10.0)

    passes = 0
    consecutive_5xx = 0
    genre_rows_written = 0
    print(f"grinding stage={args.stage} against {url}", flush=True)
    with httpx.Client(timeout=timeout) as client:
        while True:
            try:
                response = client.post(url, params=params)
            except httpx.RequestError as exc:
                print(f"request failed: {exc!r}; retrying in {args.active_wait:.0f}s", flush=True)
                time.sleep(args.active_wait)
                continue

            if response.status_code == 409:
                print(f"pass already active; waiting {args.active_wait:.0f}s", flush=True)
                time.sleep(args.active_wait)
                continue
            if response.status_code >= 500:
                # A transient upstream/server wobble must not kill an overnight
                # grind; only a persistent streak means something is truly wrong.
                consecutive_5xx += 1
                if consecutive_5xx >= 20:
                    print(
                        f"giving up after {consecutive_5xx} consecutive 5xx responses", flush=True
                    )
                    return 1
                wait = min(args.active_wait * consecutive_5xx, 120.0)
                print(
                    f"server {response.status_code} ({consecutive_5xx} in a row); "
                    f"retrying in {wait:.0f}s: {response.text[:200]}",
                    flush=True,
                )
                time.sleep(wait)
                continue
            if response.status_code != 200:
                print(f"unexpected {response.status_code}: {response.text[:400]}", flush=True)
                return 1

            consecutive_5xx = 0
            body = response.json()
            passes += 1
            genre_rows_written += int(body.get("artist_genre_rows_written", 0))
            print(f"pass {passes}: {summarize(body)}", flush=True)

            if not pass_did_work(body):
                print(f"drained after {passes} pass(es).", flush=True)
                _recompute_on_drain(client, recompute_url, genre_rows_written, args)
                return 0
            if args.max_passes and passes >= args.max_passes:
                print(f"stopping after {passes} pass(es) (--max-passes).", flush=True)
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
