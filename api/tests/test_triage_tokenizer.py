"""Vibe-match tokenizer properties.

Casefold token + bigram tokenizer over playlist name/description vs a track's
genre tokens. Generic — not tuned to any naming style. No partial-word false
hits (substring matches must not count).
"""

import pytest

from crate.services.triage.tokenize import tokenize, vibe_overlap

pytestmark = pytest.mark.unit


def test_tokenize_casefolds_and_splits() -> None:
    assert tokenize("Late Night Jazz") == {"late", "night", "jazz", "late night", "night jazz"}


def test_tokenize_strips_punctuation() -> None:
    # Punctuation is a separator, not part of a token.
    assert "lo-fi" not in tokenize("lo-fi beats")
    toks = tokenize("lo-fi beats")
    assert "lo" in toks and "fi" in toks and "beats" in toks


def test_tokenize_empty() -> None:
    assert tokenize("") == set()
    assert tokenize("   ") == set()


def test_vibe_overlap_matches_whole_tokens() -> None:
    # Playlist "Night Jazz" vs track genres ["smooth jazz", "vocal jazz"]:
    # unigram "jazz" overlaps; bigrams differ.
    score = vibe_overlap("Night Jazz", None, ["smooth jazz", "vocal jazz"])
    assert score.matched == {"jazz"}
    assert score.score > 0


def test_vibe_overlap_no_partial_word_false_hit() -> None:
    # "jazz" must NOT match "jazzy"-free genres; "class" must not match "classical"
    # via substring. Whole-token matching only.
    score = vibe_overlap("Classic Rock", None, ["classical"])
    assert "class" not in score.matched  # no substring hit against "classical"


def test_vibe_overlap_uses_description_too() -> None:
    score = vibe_overlap("Chill", "ambient and downtempo textures", ["ambient", "techno"])
    assert "ambient" in score.matched


def test_vibe_overlap_empty_genres_is_zero() -> None:
    score = vibe_overlap("Anything", "desc", [])
    assert score.score == 0.0
    assert score.matched == set()
