"""Backfill album release dates onto tracks from Spotify's /v1/albums.

Every track carries an album_spotify_id but no release date yet. This walks the
distinct album ids of a user's library, fetches them 20 at a time (Spotify's
/albums cap), and writes release_date / release_date_precision / release_year
onto every track sharing each album. Run-twice-safe: only tracks still missing
a release_year are considered, so a re-run resumes where a previous run stopped
(and re-fetches only albums it never resolved).

Uses the user's stored Spotify credential exactly as sync does
(spotify_client_for_user handles token refresh, 429 backoff, and reauth), so
the only thing the environment needs is the running server's SPOTIFY_CLIENT_ID
and the encrypted credential already in the database.

    cd api && uv run python ../scripts/backfill_release_dates.py            # user: jt-dev
    cd api && uv run python ../scripts/backfill_release_dates.py --user someone
    cd api && uv run python ../scripts/backfill_release_dates.py --dry-run  # count only, no writes
"""

import argparse
import asyncio
import sys

from sqlmodel import Session, col, create_engine, select

from crate.model.orm import Track, User
from crate.services.insights.release_dates import parse_release_year
from crate.services.mutations.wiring import spotify_client_for_user
from crate.settings import get_settings

_ALBUMS_BATCH = 20


def _distinct_unresolved_album_ids(session: Session, user_id: int) -> list[str]:
    """Album ids on the user's tracks that still lack a release_year.

    Scoped to the tracks in the user's playlists (via a join on
    playlist_tracks) so a shared catalog isn't walked for every account.
    """
    from crate.model.orm import PlaylistTrack

    rows = session.exec(
        select(Track.album_spotify_id)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user_id)
        .where(col(Track.album_spotify_id).is_not(None))
        .where(col(Track.release_year).is_(None))
        .distinct()
    ).all()
    return sorted({album_id for album_id in rows if album_id})


def _apply_album(session: Session, album_id: str, release_date: str | None, precision: str | None) -> int:
    """Write the date onto every track for one album; return rows updated."""
    year = parse_release_year(release_date)
    tracks = session.exec(select(Track).where(Track.album_spotify_id == album_id)).all()
    updated = 0
    for track in tracks:
        track.release_date = release_date
        track.release_date_precision = precision
        track.release_year = year
        session.add(track)
        updated += 1
    return updated


async def _run(user_key: str, dry_run: bool) -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.clerk_user_id == user_key)).first()
        if user is None:
            print(f"no user with clerk_user_id {user_key!r}", file=sys.stderr)
            return 1
        assert user.id is not None

        album_ids = _distinct_unresolved_album_ids(session, user.id)
        print(f"{len(album_ids)} unresolved albums for user {user_key!r}", flush=True)
        if dry_run:
            return 0
        if not album_ids:
            print("nothing to backfill.", flush=True)
            return 0

        albums_resolved = 0
        albums_missing = 0
        tracks_dated = 0
        async with spotify_client_for_user(session, user) as client:
            for start in range(0, len(album_ids), _ALBUMS_BATCH):
                batch = album_ids[start : start + _ALBUMS_BATCH]
                albums = await client.get_albums(batch)
                by_id = {album["id"]: album for album in albums if album.get("id")}
                for album_id in batch:
                    album = by_id.get(album_id)
                    if album is None:
                        albums_missing += 1
                        continue
                    albums_resolved += 1
                    tracks_dated += _apply_album(
                        session,
                        album_id,
                        album.get("release_date"),
                        album.get("release_date_precision"),
                    )
                session.commit()
                done = min(start + _ALBUMS_BATCH, len(album_ids))
                print(
                    f"  {done}/{len(album_ids)} albums · resolved={albums_resolved} "
                    f"missing={albums_missing} tracks_dated={tracks_dated}",
                    flush=True,
                )

        print(
            f"done: albums_resolved={albums_resolved} albums_missing={albums_missing} "
            f"tracks_dated={tracks_dated}",
            flush=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="jt-dev", help="clerk_user_id of the target user.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count unresolved albums without fetching or writing."
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.user, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
