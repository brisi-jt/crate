"""Backfill artist photos onto catalog artists from Spotify's /v1/artists.

Track artist refs never carry images, so artist photos only arrive via the
full /v1/artists objects. This walks the catalog artists still missing a photo,
fetches them 50 at a time (Spotify's /artists cap), and writes image_url /
image_url_sm. Run-twice-safe: only artists still missing image_url are
considered, so a re-run resumes where a previous run stopped (an artist whose
Spotify object genuinely has no images stays null and is retried next run).

Uses the user's stored Spotify credential exactly as sync does
(spotify_client_for_user handles token refresh, 429 backoff, and reauth), so
the only thing the environment needs is the running server's SPOTIFY_CLIENT_ID
and the encrypted credential already in the database. Runs in its own process,
mirroring scripts/backfill_release_dates.py — it does not touch the API server.

    cd api && uv run python ../scripts/backfill_artist_images.py            # credential: jt-dev
    cd api && uv run python ../scripts/backfill_artist_images.py --user someone
    cd api && uv run python ../scripts/backfill_artist_images.py --dry-run  # count only, no writes
"""

import argparse
import asyncio
import sys

from sqlmodel import Session, create_engine, select

from crate.model.orm import User
from crate.services.imagery import _unimaged_artist_ids, backfill_artist_images
from crate.services.mutations.wiring import spotify_client_for_user
from crate.settings import get_settings


async def _run(user_key: str, dry_run: bool) -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.clerk_user_id == user_key)).first()
        if user is None:
            print(f"no user with clerk_user_id {user_key!r}", file=sys.stderr)
            return 1

        artist_ids = _unimaged_artist_ids(session)
        print(f"{len(artist_ids)} unimaged catalog artists", flush=True)
        if dry_run:
            return 0
        if not artist_ids:
            print("nothing to backfill.", flush=True)
            return 0

        # The catalog is shared, but the credential is per-user: fetch through
        # the target user's client.
        async with spotify_client_for_user(session, user) as client:
            report = await backfill_artist_images(session, client)

        print(
            f"done: artists_fetched={report.artists_fetched} "
            f"artists_missing={report.artists_missing} artists_imaged={report.artists_imaged}",
            flush=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user", default="jt-dev", help="clerk_user_id whose Spotify credential is used."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count unimaged artists without fetching or writing.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.user, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
