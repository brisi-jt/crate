"""F-series engines: ORM loaders that feed the pure metric modules.

Each ``build_*`` loads its tables once and returns the payload its endpoint
serves. Exercised over the shared analytics micro-fixture plus a little extra
seeding (ENAO genres for obscurity, top-item snapshots for drift, plays for
rhythm).
"""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from crate.model.enums import PlayEventSource, TopItemKind, TopTimeRange
from crate.model.orm import (
    ArtistGenre,
    Genre,
    PlayEvent,
    TopItemsSnapshot,
    User,
)
from crate.services.competitive import engine
from tests.test_analytics_endpoints import seed_library

pytestmark = pytest.mark.unit


def _seed_genres(session: Session) -> None:
    # Artist 1 → a mainstream genre (rank 1); Artist 6 → a niche one (rank 5000).
    pop = Genre(name="pop", enao_rank=1)
    niche = Genre(name="witch house", enao_rank=5000)
    session.add(pop)
    session.add(niche)
    session.flush()
    session.add(ArtistGenre(genre_id=pop.id, artist_name="Artist 1", weight=1.0))
    session.add(ArtistGenre(genre_id=niche.id, artist_name="Artist 6", weight=1.0))
    session.commit()


class TestObscurityEngine:
    def test_library_and_playlist_scores(self, session: Session, user: User) -> None:
        seed_library(session, user)
        _seed_genres(session)
        payload = engine.build_obscurity(session, user)
        assert payload["library"]["score"] is not None
        assert payload["source"] == "enao_rank"
        assert payload["lastfm_pending"] is True
        # Playlists present with per-list scores.
        assert any(p["name"] == "Alpha" for p in payload["playlists"])


class TestRhythmEngine:
    def test_counts_and_clock_over_plays(self, session: Session, user: User) -> None:
        ids = seed_library(session, user)
        # Two plays at hour 9 (distinct minutes — played_at is unique), one at 10.
        for hour, minute in ((9, 0), (9, 15), (10, 0)):
            session.add(
                PlayEvent(
                    user_id=user.id,
                    track_id=ids["t1"],
                    played_at=datetime(2024, 6, 1, hour, minute),
                    source=PlayEventSource.recent,
                )
            )
        session.commit()
        payload = engine.build_rhythm(session, user)
        assert payload["total_plays"] == 3
        assert payload["clock"]["peak_hour"] == 9
        assert payload["range"] == "all_time"

    def test_since_crate_range_excludes_imports(self, session: Session, user: User) -> None:
        ids = seed_library(session, user)
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=ids["t1"],
                played_at=datetime(2020, 1, 1, 9, 0),
                source=PlayEventSource.import_,
            )
        )
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=ids["t1"],
                played_at=datetime(2024, 6, 1, 9, 0),
                source=PlayEventSource.recent,
            )
        )
        session.commit()
        all_time = engine.build_rhythm(session, user, range_="all_time")
        since = engine.build_rhythm(session, user, range_="since_crate")
        assert all_time["total_plays"] == 2
        assert since["total_plays"] == 1


class TestDriftEngine:
    def test_timeline_lists_snapshots(self, session: Session, user: User) -> None:
        seed_library(session, user)
        session.add(
            TopItemsSnapshot(
                user_id=user.id,
                kind=TopItemKind.track,
                time_range=TopTimeRange.short,
                captured_at=datetime(2024, 1, 1, tzinfo=UTC),
                items=[{"rank": 1, "spotify_id": "sp-t1", "name": "Track 1"}],
            )
        )
        session.commit()
        payload = engine.build_drift(session, user)
        assert len(payload["timeline"]) == 1
        assert payload["timeline"][0]["kind"] == "track"

    def test_comparison_against_a_snapshot(self, session: Session, user: User) -> None:
        seed_library(session, user)
        snap = TopItemsSnapshot(
            user_id=user.id,
            kind=TopItemKind.track,
            time_range=TopTimeRange.short,
            captured_at=datetime(2024, 1, 1, tzinfo=UTC),
            items=[{"rank": 1, "spotify_id": "sp-t1", "name": "Track 1"}],
        )
        session.add(snap)
        session.commit()
        session.refresh(snap)
        payload = engine.build_drift(session, user, snapshot_id=snap.id)
        assert payload["comparison"] is not None
        assert "axes" in payload["comparison"]

    def test_no_snapshots_is_empty_timeline(self, session: Session, user: User) -> None:
        seed_library(session, user)
        payload = engine.build_drift(session, user)
        assert payload["timeline"] == []
        assert payload["comparison"] is None


class TestQualityEngine:
    def test_per_playlist_quality(self, session: Session, user: User) -> None:
        seed_library(session, user)
        payload = engine.build_quality(session, user)
        by_name = {p["name"]: p for p in payload["playlists"]}
        assert "Alpha" in by_name
        assert by_name["Alpha"]["score"] is not None
        refs = {s["ref"] for s in by_name["Alpha"]["subscores"]}
        assert "quality_cohesion" in refs

    def test_shared_isrc_duplicate_lowers_uniqueness(self, session: Session, user: User) -> None:
        # In the fixture, t5 and t6 share an ISRC and both live in Gamma, so
        # Gamma has one recording-level duplicate → uniqueness below 1.0. Alpha
        # (no duplicate) stays at 1.0.
        seed_library(session, user)
        payload = engine.build_quality(session, user)
        by_name = {p["name"]: p for p in payload["playlists"]}

        def uniqueness(name: str) -> float:
            return next(
                s["value"] for s in by_name[name]["subscores"] if s["ref"] == "quality_uniqueness"
            )

        assert uniqueness("Gamma") < 1.0
        assert uniqueness("Alpha") == 1.0


class TestArcPreviewEngine:
    def test_preview_returns_permutation_and_scores(self, session: Session, user: User) -> None:
        ids = seed_library(session, user)
        # Alpha = [t1,t2,t3,t4], all enriched.
        preview = engine.build_arc_preview(session, user, ids["Alpha"], mood="rising")
        assert preview is not None
        current_ids = [ids[f"t{i}"] for i in (1, 2, 3, 4)]
        assert sorted(preview["suggested_order"]) == sorted(current_ids)
        assert preview["current_flow"] is not None
        assert preview["suggested_flow"] is not None
        assert preview["mood"] == "rising"

    def test_preview_below_floor_is_none(self, session: Session, user: User) -> None:
        ids = seed_library(session, user)
        # Beta = [t3,t4,t5] is exactly 3, so still previewable; make a 2-track case.
        from crate.model.orm import Playlist, PlaylistTrack

        pl = Playlist(user_id=user.id, spotify_id="sp-Tiny", name="Tiny", is_owned=True)
        session.add(pl)
        session.flush()
        for pos, i in enumerate((1, 2)):
            session.add(
                PlaylistTrack(
                    user_id=user.id, playlist_id=pl.id, track_id=ids[f"t{i}"], position=pos
                )
            )
        session.commit()
        assert engine.build_arc_preview(session, user, pl.id, mood="rising") is None
