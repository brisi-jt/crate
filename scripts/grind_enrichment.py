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
    """True while the selected stage still has un-enriched rows to process."""
    return bool(
        body.get("tracks_processed", 0)
        or body.get("features_from_localdsp", 0)
        or body.get("artists_processed", 0)
        or body.get("artists_mbid_resolved", 0)
    )


def summarize(body: dict) -> str:
    parts = [
        f"tracks={body.get('tracks_processed', 0)}",
        f"recco={body.get('features_from_reccobeats', 0)}",
        f"isrc={body.get('features_from_isrc_fallback', 0)}",
        f"freqblog={body.get('features_from_freqblog', 0)}",
        f"localdsp={body.get('features_from_localdsp', 0)}",
        f"missing={body.get('features_missing', 0)}",
        f"mbid={body.get('artists_mbid_resolved', 0)}",
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
    parser.add_argument("--max-passes", type=int, default=0, help="Stop after N passes (0 = until drained).")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    url = f"{base_url}/v1/enrichment/run"
    params = {
        "stage": args.stage,
        "batch_size": args.batch_size,
        "time_budget_seconds": args.time_budget,
    }
    # No read timeout: a pass is server-bounded by its wall-clock budget, so the
    # client just waits for it to return (with headroom over the 600s cap).
    timeout = httpx.Timeout(connect=10.0, read=args.time_budget + 120, write=10.0, pool=10.0)

    passes = 0
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
            if response.status_code != 200:
                print(f"unexpected {response.status_code}: {response.text[:400]}", flush=True)
                return 1

            body = response.json()
            passes += 1
            print(f"pass {passes}: {summarize(body)}", flush=True)

            if not pass_did_work(body):
                print(f"drained after {passes} pass(es).", flush=True)
                return 0
            if args.max_passes and passes >= args.max_passes:
                print(f"stopping after {passes} pass(es) (--max-passes).", flush=True)
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
