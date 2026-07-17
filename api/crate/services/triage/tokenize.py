"""Vibe-match tokenizer: playlist name/description vs track genre tokens.

Generic token/bigram overlap, casefolded, whole-token only (no substring
matches). Not tuned to any naming convention — a playlist named "Late Night
Jazz" and a track tagged "smooth jazz" overlap on the unigram "jazz"; the
matching stays word-level so "classical" never matches "class".
"""

import re
from dataclasses import dataclass
from itertools import pairwise

# Word characters only; every run of non-word chars (space, hyphen, slash,
# punctuation) separates tokens. Digits stay (e.g. "80s", "2step").
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _words(text: str) -> list[str]:
    return [m.group(0).casefold() for m in _WORD.finditer(text)]


def tokenize(text: str) -> set[str]:
    """Casefolded unigrams + adjacent bigrams of ``text``.

    Bigrams let "night jazz" match a genre phrase without a substring test;
    unigrams keep single-word overlaps. Empty/whitespace text yields no tokens.
    """
    words = _words(text)
    tokens: set[str] = set(words)
    for a, b in pairwise(words):
        tokens.add(f"{a} {b}")
    return tokens


@dataclass(frozen=True)
class VibeOverlap:
    """The whole-token overlap between a playlist's text and a track's genres."""

    matched: set[str]
    score: float


def vibe_overlap(name: str, description: str | None, genres: list[str]) -> VibeOverlap:
    """Whole-token overlap of playlist name+description against track genres.

    Both sides are tokenized (unigrams + bigrams); the score is the Jaccard-like
    ratio of shared tokens to the genre-token count, so a genre-poor track can't
    be over-credited. Returns 0 with no genres — nothing to match.
    """
    if not genres:
        return VibeOverlap(matched=set(), score=0.0)
    playlist_tokens = tokenize(name) | tokenize(description or "")
    genre_tokens: set[str] = set()
    for genre in genres:
        genre_tokens |= tokenize(genre)
    if not genre_tokens:
        return VibeOverlap(matched=set(), score=0.0)
    matched = playlist_tokens & genre_tokens
    return VibeOverlap(matched=matched, score=len(matched) / len(genre_tokens))
