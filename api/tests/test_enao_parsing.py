"""ENAO dump parsing: genres, artist exemplars, and sub-genre tag weights."""

import json

import pytest

from crate.services.enrichment.enao import (
    EXEMPLAR_WEIGHT,
    aggregate_artist_genres,
    parse_genres,
    split_artist_credit,
)

pytestmark = pytest.mark.unit


GENRE_LINES = [
    json.dumps({"url": "?root=pop&scope=all", "name": "pop"}),
    json.dumps({"url": "?root=chillwave&scope=all", "name": "chillwave"}),
    json.dumps({"url": "?root=indietronica&scope=all", "name": "indietronica"}),
]

SONG_LINES = [
    json.dumps(
        {
            "genre": "chillwave",
            "songs": [
                {"position": "1", "name": "Feel It All Around", "artist": "Washed Out"},
                {"position": "2", "name": "Sheila", "artist": "Atlas Sound"},
                {"position": "3", "name": "Eyes Be Closed", "artist": "Washed Out"},
            ],
        }
    ),
]

TAG_LINES = [
    json.dumps(
        {
            "genre": "chillwave",
            "artist": "Washed Out",
            "track": "Feel It All Around",
            "tags": [
                {"count": 100, "tag": "chillwave"},
                {"count": 40, "tag": "Indietronica"},
                {"count": 25, "tag": "dreamy"},
            ],
        }
    ),
]


def test_parse_genres_keeps_popularity_order() -> None:
    genres = parse_genres(GENRE_LINES)
    assert genres == [("pop", 1), ("chillwave", 2), ("indietronica", 3)]


def test_exemplar_appearances_accumulate_weight() -> None:
    weights = aggregate_artist_genres(SONG_LINES, [], {"pop", "chillwave", "indietronica"})
    assert weights[("chillwave", "Washed Out")] == pytest.approx(2 * EXEMPLAR_WEIGHT)
    assert weights[("chillwave", "Atlas Sound")] == pytest.approx(EXEMPLAR_WEIGHT)


def test_subgenre_tags_add_weight_case_insensitively() -> None:
    weights = aggregate_artist_genres(SONG_LINES, TAG_LINES, {"pop", "chillwave", "indietronica"})
    # "Indietronica" tag matches the indietronica genre despite its casing.
    assert weights[("indietronica", "Washed Out")] == pytest.approx(40.0)
    # "dreamy" is not a genre, so it contributes nothing.
    assert ("dreamy", "Washed Out") not in weights


def test_own_genre_tag_is_not_double_counted() -> None:
    weights = aggregate_artist_genres(SONG_LINES, TAG_LINES, {"pop", "chillwave", "indietronica"})
    # The song's own genre already carries exemplar weight; its matching tag
    # ("chillwave", count 100) must not inflate it.
    assert weights[("chillwave", "Washed Out")] == pytest.approx(2 * EXEMPLAR_WEIGHT)


def test_multi_artist_credits_are_split() -> None:
    assert split_artist_credit("B.o.B, Hayley Williams") == ["B.o.B", "Hayley Williams"]
    assert split_artist_credit("Washed Out") == ["Washed Out"]
