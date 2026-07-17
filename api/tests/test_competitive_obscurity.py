"""F3 obscurity — pure scoring over ENAO genre ranks.

Obscurity is grounded in Every Noise's genre popularity ordering: a track's
artists map to genres, each genre carries an ``enao_rank`` (1 = most popular).
A track filed under mainstream genres scores low obscurity; a track under only
niche (high-rank) genres or with no genre data at all scores high. The
Last.fm listener-count upgrade is not wired (no key yet) — the metric reports
its source as ENAO and flags the pending upgrade, never fabricating a value.
"""

import pytest

from crate.services.competitive.obscurity import (
    ENAO_GENRE_COUNT,
    obscurity_report,
    track_obscurity,
)

pytestmark = pytest.mark.unit


class TestTrackObscurity:
    def test_mainstream_genre_is_low_obscurity(self) -> None:
        # Rank 1 of ~6000 → near the popular pole → obscurity near 0.
        score = track_obscurity([1])
        assert score is not None
        assert score < 0.05

    def test_niche_genre_is_high_obscurity(self) -> None:
        # A genre near the tail of the ordering → obscurity near 1.
        score = track_obscurity([ENAO_GENRE_COUNT])
        assert score is not None
        assert score > 0.95

    def test_multiple_genres_take_the_most_mainstream(self) -> None:
        # A track that touches one mainstream genre is not obscure even if it
        # also touches niche ones — its most-popular genre anchors it.
        assert track_obscurity([1, ENAO_GENRE_COUNT]) == track_obscurity([1])

    def test_no_genre_data_is_max_obscurity(self) -> None:
        # No ENAO rank for any of the track's genres = maximally obscure
        # (nothing places it on the popularity map).
        assert track_obscurity([]) == 1.0

    def test_score_is_monotonic_in_rank(self) -> None:
        assert track_obscurity([10]) < track_obscurity([100]) < track_obscurity([1000])


class TestObscurityReport:
    def test_library_mean_over_scored_tracks(self) -> None:
        # Two mainstream tracks, one niche: mean obscurity sits between.
        track_ranks = {1: [1], 2: [2], 3: [ENAO_GENRE_COUNT]}
        report = obscurity_report(track_ranks, playlists={})
        assert 0.0 < report["library"]["score"] < 1.0
        assert report["library"]["scored_tracks"] == 3
        # ENAO is the current source; the Last.fm listener upgrade is pending.
        assert report["source"] == "enao_rank"
        assert report["lastfm_pending"] is True

    def test_per_playlist_scores(self) -> None:
        track_ranks = {1: [1], 2: [ENAO_GENRE_COUNT]}
        playlists = {
            10: {"name": "Pop", "track_ids": [1]},
            11: {"name": "Deep Cuts", "track_ids": [2]},
        }
        report = obscurity_report(track_ranks, playlists=playlists)
        by_id = {p["playlist_id"]: p for p in report["playlists"]}
        assert by_id[10]["score"] < by_id[11]["score"]
        assert by_id[10]["name"] == "Pop"
        assert by_id[10]["scored_tracks"] == 1

    def test_playlist_with_no_scored_tracks_reports_null(self) -> None:
        report = obscurity_report({}, playlists={10: {"name": "Empty", "track_ids": []}})
        by_id = {p["playlist_id"]: p for p in report["playlists"]}
        assert by_id[10]["score"] is None
        assert by_id[10]["scored_tracks"] == 0

    def test_empty_library_reports_null_score(self) -> None:
        report = obscurity_report({}, playlists={})
        assert report["library"]["score"] is None
        assert report["library"]["scored_tracks"] == 0

    def test_playlists_sorted_most_obscure_first(self) -> None:
        track_ranks = {1: [1], 2: [ENAO_GENRE_COUNT]}
        playlists = {
            10: {"name": "Pop", "track_ids": [1]},
            11: {"name": "Deep Cuts", "track_ids": [2]},
        }
        report = obscurity_report(track_ranks, playlists=playlists)
        scores = [p["score"] for p in report["playlists"] if p["score"] is not None]
        assert scores == sorted(scores, reverse=True)
