"""Backfill album art onto tracks from Spotify's /v1/albums.

Every owned-library track carries an album_spotify_id but rows predating the
imagery columns have no album art. This walks the distinct album ids of a
user's library, fetches them 20 at a time (Spotify's /albums cap), and writes
image_url / image_url_sm onto every track sharing each album. Run-twice-safe:
only tracks still missing image_url are considered, so a re-run resumes where a
previous run stopped.

Uses the user's stored Spotify credential exactly as sync does
(spotify_client_for_user handles token refresh, 429 backoff, and reauth), so
the only thing the environment needs is the running server's SPOTIFY_CLIENT_ID
and the encrypted credential already in the database. Runs in its own process,
mirroring scripts/backfill_release_dates.py — it does not touch the API server.

    cd api && uv run python ../scripts/backfill_album_art.py            # user: jt-dev
    cd api && uv run python ../scripts/backfill_album_art.py --user someone
    cd api && uv run python ../scripts/backfill_album_art.py --dry-run  # count only, no writes
"""

import argparse
import asyncio
import sys

from sqlmodel import Session, create_engine, select

from crate.model.orm import User
from crate.services.imagery import _unimaged_album_ids, backfill_album_art
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
        assert user.id is not None

        album_ids = _unimaged_album_ids(session, user.id)
        print(f"{len(album_ids)} unimaged albums for user {user_key!r}", flush=True)
        if dry_run:
            return 0
        if not album_ids:
            print("nothing to backfill.", flush=True)
            return 0

        async with spotify_client_for_user(session, user) as client:
            report = await backfill_album_art(session, user, client)

        print(
            f"done: albums_fetched={report.albums_fetched} "
            f"albums_missing={report.albums_missing} tracks_imaged={report.tracks_imaged}",
            flush=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="jt-dev", help="clerk_user_id of the target user.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count unimaged albums without fetching or writing."
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.user, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
