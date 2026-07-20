"""Re-arm the artist name-search fallback for artists still without an MBID.

The identity stage only visits artists whose ``mbid_checked_at`` is null (so the
un-resolvable long tail isn't re-queried every pass). After the ISRC ladder ran,
~11k artists were marked checked with no MBID because their tracks carry no
MusicBrainz-matchable ISRC. The name-search fallback is exactly for those
artists, so this script clears the marker on artists that still have no MBID,
letting the next ``identity`` grind try a name search for each.

Idempotent and safe: it only touches rows where ``mbid IS NULL`` (never an
already-resolved artist), and re-running once the search has re-marked them is a
no-op-shaped update (they're checked again). Prints the affected count.

    cd api && uv run python ../scripts/reset_name_search_marker.py           # apply
    cd api && uv run python ../scripts/reset_name_search_marker.py --dry-run # count only
"""

import argparse

from sqlalchemy import text
from sqlmodel import Session, create_engine

from crate.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many artists would be re-armed without changing anything.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the database (defaults to the configured DATABASE_URL).",
    )
    args = parser.parse_args()

    engine = create_engine(args.database_url or get_settings().database_url)
    with Session(engine) as session:
        pending = session.exec(
            text("SELECT COUNT(*) FROM artists WHERE mbid IS NULL AND mbid_checked_at IS NOT NULL")
        ).one()[0]
        print(f"artists without an MBID, currently marked checked: {pending}")
        if args.dry_run:
            print("dry run — no changes made")
            return 0
        result = session.exec(
            text(
                "UPDATE artists SET mbid_checked_at = NULL "
                "WHERE mbid IS NULL AND mbid_checked_at IS NOT NULL"
            )
        )
        session.commit()
        print(f"re-armed {result.rowcount} artists for a name-search attempt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
