"""Scrub control characters and lone surrogates from stored names.

A raw control character or lone UTF-16 surrogate in a track / artist / playlist
name breaks strict JSON consumers of the API (``jq``: "Invalid control
character"; a lone surrogate raises UnicodeEncodeError → a truncated body).
Ingest now scrubs names going forward (crate.services.text.clean_name), and the
API has a response-level guard, but any rows written before that fix keep their
corrupt bytes until this one-off backfill cleans them.

Idempotent / run-twice-safe: it selects only rows whose name still contains a
control char or surrogate and rewrites them to the cleaned value, so a second
run finds nothing to do. Non-destructive — it only rewrites the offending
name fields, nothing else.

    cd api && uv run python ../scripts/scrub_control_chars.py            # scrub the live DB
    cd api && uv run python ../scripts/scrub_control_chars.py --dry-run  # report counts only
"""

import argparse

from sqlmodel import Session, create_engine, select

from crate.model.orm import Artist, Playlist, Track
from crate.services.text import clean_name, clean_optional_name
from crate.settings import get_settings

_COMMIT_EVERY = 500


def _dirty(value: str | None) -> bool:
    return value is not None and clean_name(value) != value


def scrub(session: Session, *, dry_run: bool) -> dict[str, int]:
    counts = {"tracks": 0, "artists": 0, "playlists": 0}

    for track in session.exec(select(Track)).all():
        changed = False
        if _dirty(track.name):
            if not dry_run:
                track.name = clean_name(track.name)
            changed = True
        if _dirty(track.album_name):
            if not dry_run:
                track.album_name = clean_optional_name(track.album_name)
            changed = True
        cleaned_artists = [
            {**a, "name": clean_optional_name(a.get("name"))} for a in track.artists
        ]
        if cleaned_artists != track.artists:
            if not dry_run:
                track.artists = cleaned_artists
            changed = True
        if changed:
            counts["tracks"] += 1
            if not dry_run:
                session.add(track)
                if counts["tracks"] % _COMMIT_EVERY == 0:
                    session.commit()

    for artist in session.exec(select(Artist)).all():
        if _dirty(artist.name):
            counts["artists"] += 1
            if not dry_run:
                artist.name = clean_name(artist.name)
                session.add(artist)
                if counts["artists"] % _COMMIT_EVERY == 0:
                    session.commit()

    for playlist in session.exec(select(Playlist)).all():
        changed = False
        if _dirty(playlist.name):
            if not dry_run:
                playlist.name = clean_name(playlist.name)
            changed = True
        if _dirty(playlist.description):
            if not dry_run:
                playlist.description = clean_optional_name(playlist.description)
            changed = True
        if changed:
            counts["playlists"] += 1
            if not dry_run:
                session.add(playlist)

    if not dry_run:
        session.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Count offending rows without writing."
    )
    args = parser.parse_args()

    engine = create_engine(get_settings().database_url)
    with Session(engine) as session:
        counts = scrub(session, dry_run=args.dry_run)
    verb = "would scrub" if args.dry_run else "scrubbed"
    print(
        f"{verb}: tracks={counts['tracks']} artists={counts['artists']} "
        f"playlists={counts['playlists']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
