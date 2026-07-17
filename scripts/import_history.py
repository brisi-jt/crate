"""Import a lifetime Spotify "extended streaming history" export into crate.

Spotify's privacy page lets you request your *extended* streaming history; it
arrives (as a zip, weeks later) containing ``Streaming_History_Audio_*.json``
files. Unzip them into a drop directory and point this script at it. Each line
whose track is already in your crate library becomes a ``play_events`` row
(source ``import``, so listening analytics can separate all-time from
since-crate); lines whose track is not yet in the library are parked in
``history_import_reviews`` for a later re-resolution pass, and podcast /
zero-listen lines are recorded as skipped.

Run-twice-safe: play_events dedupe on (user, played_at) and reviews on
(user, content_key), so re-importing the same export adds nothing.

    # Real import (writes to the live crate DB — this is JT's manual step):
    cd api && uv run python ../scripts/import_history.py --path ~/spotify-export

    # Dry run — parse + report, write nothing:
    cd api && uv run python ../scripts/import_history.py --path ~/spotify-export --dry-run

    # Import a fixture into the isolated crate_test DB (never the live one):
    cd api && uv run python ../scripts/import_history.py \\
        --path tests/fixtures/history --target crate_test

Uses the same settings module as the server; the only environment it needs is
the database URL (settings default points at the compose MySQL on :3308). Runs
in its own process, mirroring scripts/backfill_album_art.py — it does not touch
the API server or Spotify.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

from crate.model.orm import User
from crate.services.history.service import import_export
from crate.settings import get_settings


def _resolve_url(default_url: str, database: str | None, target: str | None) -> str:
    """Pick the database URL, honouring --database (full URL) / --target (name).

    --target is a convenience for pointing at a sibling database on the same
    server (e.g. ``crate_test`` for fixture imports) without retyping the URL.
    """
    if database:
        return database
    if target:
        return make_url(default_url).set(database=target).render_as_string(
            hide_password=False
        )
    return default_url


def _run(user_key: str, path: Path, dry_run: bool, url: str) -> int:
    engine = create_engine(url)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.clerk_user_id == user_key)).first()
        if user is None:
            print(f"no user with clerk_user_id {user_key!r}", file=sys.stderr)
            return 1

        report = import_export(session, user, path, dry_run=dry_run)

    parsed = report.parsed
    print(
        f"read {report.records_read} records from {path} "
        f"({len(parsed.plays)} plays, {len(parsed.skipped)} non-plays)",
        flush=True,
    )
    if report.ingest is None:
        print("dry run — nothing written.", flush=True)
        return 0

    ing = report.ingest
    print(
        f"done: ingested={ing.ingested} resolved={ing.resolved} parked={ing.parked} "
        f"skipped_parked={ing.skipped_parked} duplicate_plays={ing.duplicate_plays} "
        f"duplicate_reviews={ing.duplicate_reviews}",
        flush=True,
    )
    if ing.errors:
        print(f"{len(ing.errors)} errors:", file=sys.stderr)
        for err in ing.errors:
            print(f"  {err}", file=sys.stderr)
    return 0


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        required=True,
        type=Path,
        help="Export directory (of Streaming_History_Audio_*.json) or a single file.",
    )
    parser.add_argument(
        "--user",
        default=settings.dev_user or "jt-dev",
        help="clerk_user_id of the target user.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing any rows.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Full database URL override (default: the settings database_url).",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Sibling database name on the same server (e.g. crate_test for fixtures).",
    )
    args = parser.parse_args()
    url = _resolve_url(settings.database_url, args.database, args.target)
    return _run(args.user, args.path, args.dry_run, url)


if __name__ == "__main__":
    raise SystemExit(main())
