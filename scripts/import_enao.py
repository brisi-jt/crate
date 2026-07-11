"""Import the Every Noise at Once genre dump into crate's database.

Loads genres (with popularity rank) and artist↔genre weights from the
trebi/music-genres-dataset dump into the genres / artist_genres tables.
Re-running is safe: genres upsert by name, memberships by (genre, artist).

Run from api/ so crate and its database driver are importable:

    cd api && uv run python ../scripts/import_enao.py            # downloads the dump
    cd api && uv run python ../scripts/import_enao.py --zip /path/to/data.zip
"""

import argparse
import io
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlmodel import Session, create_engine, select

from crate.model.orm import ArtistGenre, Genre
from crate.model.orm.base import utcnow
from crate.services.enrichment.enao import aggregate_artist_genres, parse_genres
from crate.settings import get_settings

# The dataset repo stores data.zip in Git LFS; this endpoint serves the real
# object (the plain raw URL returns only the LFS pointer file).
DATASET_URL = "https://media.githubusercontent.com/media/trebi/music-genres-dataset/master/data.zip"

INSERT_CHUNK = 5000


def download_dataset(destination: Path) -> None:
    print(f"downloading {DATASET_URL} ...")
    with (
        destination.open("wb") as fh,
        httpx.stream("GET", DATASET_URL, follow_redirects=True, timeout=120.0) as response,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes():
            fh.write(chunk)
    print(f"downloaded {destination.stat().st_size / 1e6:.1f} MB")


def read_lines(archive: zipfile.ZipFile, name: str) -> list[str]:
    with archive.open(name) as fh:
        return io.TextIOWrapper(fh, encoding="utf-8").readlines()


def upsert_genres(session: Session, genres: list[tuple[str, int]]) -> dict[str, int]:
    """Insert or refresh genre rows; returns name → id."""
    existing = {row.name: row for row in session.exec(select(Genre)).all()}
    for name, rank in genres:
        row = existing.get(name)
        if row is None:
            session.add(Genre(name=name, enao_rank=rank))
        elif row.enao_rank != rank:
            row.enao_rank = rank
            session.add(row)
    session.commit()
    return {row.name: row.id for row in session.exec(select(Genre)).all()}


def upsert_artist_genres(
    session: Session,
    genre_ids: dict[str, int],
    weights: dict[tuple[str, str], float],
) -> None:
    now = utcnow()
    rows = [
        {
            "genre_id": genre_ids[genre],
            "artist_name": artist[:512],
            "artist_id": None,
            "weight": weight,
            "created_at": now,
            "updated_at": now,
        }
        for (genre, artist), weight in weights.items()
        if genre in genre_ids
    ]
    table = ArtistGenre.__table__
    for start in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[start : start + INSERT_CHUNK]
        statement = mysql_insert(table).values(chunk)
        statement = statement.on_duplicate_key_update(
            weight=statement.inserted.weight, updated_at=statement.inserted.updated_at
        )
        session.connection().execute(statement)
        print(f"  memberships {min(start + INSERT_CHUNK, len(rows))}/{len(rows)}", end="\r")
    session.commit()
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--zip",
        type=Path,
        help="Path to a local copy of the dataset's data.zip (skips the download).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the database (defaults to the configured DATABASE_URL).",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = args.zip
        if zip_path is None:
            zip_path = Path(tmp) / "data.zip"
            download_dataset(zip_path)

        with zipfile.ZipFile(zip_path) as archive:
            print("parsing genres.jl ...")
            genres = parse_genres(read_lines(archive, "genres.jl"))
            print(f"  {len(genres)} genres")

            print("parsing songs.jl + tags.jl (sub-genre weights) ...")
            weights = aggregate_artist_genres(
                read_lines(archive, "songs.jl"),
                read_lines(archive, "tags.jl"),
                {name for name, _ in genres},
            )
            print(f"  {len(weights)} artist-genre memberships")

    engine = create_engine(args.database_url or get_settings().database_url)
    with Session(engine) as session:
        genre_ids = upsert_genres(session, genres)
        print(f"genres in database: {len(genre_ids)}")
        upsert_artist_genres(session, genre_ids, weights)

        genre_count = session.exec(select(func.count()).select_from(Genre)).one()
        membership_count = session.exec(select(func.count()).select_from(ArtistGenre)).one()
        print(f"done: {genre_count} genres, {membership_count} artist-genre rows")
        if genre_count <= 1000:
            print("ERROR: expected more than 1,000 genres", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
