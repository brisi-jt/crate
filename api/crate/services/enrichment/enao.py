"""Parsing for the Every Noise at Once genre dump (trebi/music-genres-dataset).

The dump is JSON-lines:
- genres.jl — one genre per line, in ENAO's popularity order
- songs.jl — one line per genre carrying its 200 exemplar songs
- tags.jl — one line per (genre, song) carrying Last.fm tags with counts;
  tags whose name is itself a genre act as sub-genre weights

Artist↔genre weights combine two signals on one scale: each exemplar-song
appearance is worth EXEMPLAR_WEIGHT (the strongest signal, equal to a
maximum Last.fm tag count), and each sub-genre tag adds its raw count
(0-100). Weights are comparable within a genre, not across genres.
"""

import json
from collections.abc import Iterable

# Weight of one exemplar-list appearance; matches the 0-100 scale of
# Last.fm tag counts so both signals can share one number.
EXEMPLAR_WEIGHT = 100.0


def parse_genres(lines: Iterable[str]) -> list[tuple[str, int]]:
    """(name, popularity rank) per genre, rank following file order from 1."""
    genres = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        genres.append((record["name"], len(genres) + 1))
    return genres


def split_artist_credit(credit: str) -> list[str]:
    """Split a comma-joined artist credit into individual names.

    Artist names that themselves contain ", " are mis-split — acceptable, as
    the unsplit credit string would match nothing in the catalog at all.
    """
    return [name for part in credit.split(", ") if (name := part.strip())]


def aggregate_artist_genres(
    song_lines: Iterable[str],
    tag_lines: Iterable[str],
    genre_names: set[str],
) -> dict[tuple[str, str], float]:
    """Weights keyed by (genre name, artist name).

    Exemplar-list membership comes from song_lines; sub-genre weights come
    from tag_lines entries whose tag names (case-insensitively) are genres.
    A tag matching the song's own genre is skipped — the exemplar signal
    already covers that membership.
    """
    lowered_genres = {name.lower(): name for name in genre_names}
    weights: dict[tuple[str, str], float] = {}

    for line in song_lines:
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        genre = record.get("genre")
        if genre not in genre_names:
            continue
        for song in record.get("songs", []):
            for artist in split_artist_credit(song.get("artist", "")):
                key = (genre, artist)
                weights[key] = weights.get(key, 0.0) + EXEMPLAR_WEIGHT

    for line in tag_lines:
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        own_genre = record.get("genre", "")
        artists = split_artist_credit(record.get("artist", ""))
        for tag in record.get("tags", []):
            tag_genre = lowered_genres.get(str(tag.get("tag", "")).lower())
            if tag_genre is None or tag_genre == own_genre:
                continue
            count = float(tag.get("count", 0))
            if count <= 0:
                continue
            for artist in artists:
                key = (tag_genre, artist)
                weights[key] = weights.get(key, 0.0) + count

    return weights
