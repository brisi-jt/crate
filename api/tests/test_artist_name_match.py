"""Conservative artist name-search acceptance policy.

A wrong-artist match silently poisons genres, so acceptance requires a high MB
score, exact normalized-name equality, and an unambiguous top result. These
tests pin every bar and the normalization rules.
"""

import pytest

from crate.services.enrichment.models import ArtistSearchResult
from crate.services.enrichment.orchestrator import (
    MIN_SEARCH_SCORE,
    accept_name_search_mbid,
    normalize_artist_name,
)

pytestmark = pytest.mark.unit


def result(name: str, mbid: str, score: int) -> ArtistSearchResult:
    return ArtistSearchResult(id=mbid, name=name, score=score)


def test_normalize_trims_casefolds_and_collapses_whitespace() -> None:
    assert normalize_artist_name("  Kota   the  Friend ") == "kota the friend"
    assert normalize_artist_name("MØ") == "mø"


def test_normalize_keeps_meaningful_punctuation() -> None:
    # Punctuation distinguishes real artists (P!nk vs Pink) — never stripped.
    assert normalize_artist_name("Michael Franti & Spearhead") == "michael franti & spearhead"
    assert normalize_artist_name("P!nk") == "p!nk"


def test_exact_high_score_unambiguous_match_accepts() -> None:
    candidates = [result("Kota the Friend", "mbid-1", 100)]
    assert accept_name_search_mbid("Kota the Friend", candidates) == "mbid-1"


def test_casefold_and_whitespace_differences_still_match() -> None:
    candidates = [result("kota  the friend", "mbid-1", 100)]
    assert accept_name_search_mbid("Kota the Friend", candidates) == "mbid-1"


def test_low_score_is_rejected() -> None:
    candidates = [result("Kota the Friend", "mbid-1", MIN_SEARCH_SCORE - 1)]
    assert accept_name_search_mbid("Kota the Friend", candidates) is None


def test_name_mismatch_is_rejected_even_at_score_100() -> None:
    # MB score can be 100 for a fuzzy near-name; exact-name equality is the guard.
    candidates = [result("Kota the Friends", "mbid-1", 100)]
    assert accept_name_search_mbid("Kota the Friend", candidates) is None


def test_two_passing_candidates_are_ambiguous_and_rejected() -> None:
    # Two same-named artists both clearing the bars — we cannot tell which is
    # ours, so we take neither rather than poison genres.
    candidates = [
        result("Halo", "mbid-1", 100),
        result("Halo", "mbid-2", 100),
    ]
    assert accept_name_search_mbid("Halo", candidates) is None


def test_one_passing_amid_non_matching_others_still_accepts() -> None:
    # Only the exact-name high-score candidate passes the bars; the loose ones
    # don't count toward ambiguity.
    candidates = [
        result("Kota the Friend", "mbid-1", 100),
        result("Kota", "mbid-2", 100),
        result("Kota the Friend (tribute)", "mbid-3", 90),
    ]
    assert accept_name_search_mbid("Kota the Friend", candidates) == "mbid-1"


def test_empty_candidates_rejected() -> None:
    assert accept_name_search_mbid("Nobody", []) is None
