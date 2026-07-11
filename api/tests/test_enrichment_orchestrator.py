"""Enrichment orchestrator: fallback ladder, budget, degradation, calibration."""

import pytest
from sqlmodel import Session, select

from crate.model.enums import FeatureSource, FeatureStatus, SimilaritySource, TagSource
from crate.model.orm import (
    Artist,
    ArtistSimilarity,
    ArtistTag,
    FeatureCalibration,
    FreqBlogBudget,
    Track,
    TrackFeatures,
)
from crate.services.enrichment.models import (
    ArtistTagView,
    AudioFeatures,
    IsrcRecording,
    SimilarArtist,
)
from crate.services.enrichment.orchestrator import EnrichmentService

pytestmark = pytest.mark.unit


def features(energy: float = 0.5) -> AudioFeatures:
    return AudioFeatures(energy=energy, valence=0.4, tempo=120.0)


class FakeRecco:
    def __init__(
        self,
        by_id: dict[str, AudioFeatures] | None = None,
        by_isrc: dict[str, AudioFeatures] | None = None,
    ) -> None:
        self.by_id = by_id or {}
        self.by_isrc = by_isrc or {}
        self.batch_calls: list[list[str]] = []
        self.isrc_calls: list[str] = []

    async def get_audio_features_batch(self, spotify_ids: list[str]) -> dict[str, AudioFeatures]:
        self.batch_calls.append(list(spotify_ids))
        return {i: self.by_id[i] for i in spotify_ids if i in self.by_id}

    async def get_audio_features_by_isrc(self, isrc: str) -> AudioFeatures | None:
        self.isrc_calls.append(isrc)
        return self.by_isrc.get(isrc)


class FakeFreqBlog:
    def __init__(self, by_id: dict[str, AudioFeatures] | None = None) -> None:
        self.by_id = by_id or {}
        self.calls: list[str] = []

    async def get_audio_features(self, spotify_id: str) -> AudioFeatures | None:
        self.calls.append(spotify_id)
        return self.by_id.get(spotify_id)


class FakeLastFm:
    def __init__(
        self,
        similar: dict[str, list[SimilarArtist]] | None = None,
        tags: dict[str, list[ArtistTagView]] | None = None,
    ) -> None:
        self.similar = similar or {}
        self.tags = tags or {}

    async def get_similar_artists(self, artist_name: str) -> list[SimilarArtist]:
        return self.similar.get(artist_name, [])

    async def get_artist_top_tags(self, artist_name: str) -> list[ArtistTagView]:
        return self.tags.get(artist_name, [])


class FakeMusicBrainz:
    def __init__(self, by_isrc: dict[str, IsrcRecording] | None = None) -> None:
        self.by_isrc = by_isrc or {}
        self.calls: list[str] = []

    async def lookup_isrc(self, isrc: str) -> IsrcRecording | None:
        self.calls.append(isrc)
        return self.by_isrc.get(isrc)


def add_track(session: Session, spotify_id: str, isrc: str | None = None, artists=None) -> Track:
    track = Track(spotify_id=spotify_id, isrc=isrc, name=f"t-{spotify_id}", artists=artists or [])
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def add_artist(session: Session, spotify_id: str, name: str, mbid: str | None = None) -> Artist:
    artist = Artist(spotify_id=spotify_id, name=name, mbid=mbid)
    session.add(artist)
    session.commit()
    session.refresh(artist)
    return artist


def service(**overrides) -> EnrichmentService:
    defaults = {
        "reccobeats": FakeRecco(),
        "freqblog": None,
        "lastfm": None,
        "musicbrainz": FakeMusicBrainz(),
        "freqblog_budget_limit": 1000,
        "month": "2026-07",
    }
    defaults.update(overrides)
    return EnrichmentService(**defaults)


def stored_features(session: Session, track: Track) -> TrackFeatures:
    return session.exec(select(TrackFeatures).where(TrackFeatures.track_id == track.id)).one()


class TestFeatureLadder:
    async def test_reccobeats_hit_is_persisted(self, session: Session) -> None:
        track = add_track(session, "hit1")
        svc = service(reccobeats=FakeRecco(by_id={"hit1": features(0.8)}))

        report = await svc.run(session, batch_size=10)

        row = stored_features(session, track)
        assert row.status == FeatureStatus.present
        assert row.source == FeatureSource.reccobeats
        assert row.energy == pytest.approx(0.8)
        assert report.features_from_reccobeats == 1

    async def test_miss_falls_back_to_isrc_lookup(self, session: Session) -> None:
        track = add_track(session, "miss1", isrc="ISRC001")
        recco = FakeRecco(by_isrc={"ISRC001": features(0.3)})
        svc = service(reccobeats=recco)

        report = await svc.run(session, batch_size=10)

        row = stored_features(session, track)
        assert row.source == FeatureSource.reccobeats
        assert row.energy == pytest.approx(0.3)
        assert recco.isrc_calls == ["ISRC001"]
        assert report.features_from_isrc_fallback == 1

    async def test_miss_falls_back_to_freqblog_and_consumes_budget(self, session: Session) -> None:
        track = add_track(session, "miss2", isrc="ISRC002")
        freq = FakeFreqBlog(by_id={"miss2": features(0.6)})
        svc = service(freqblog=freq, freqblog_budget_limit=5)

        report = await svc.run(session, batch_size=10)

        row = stored_features(session, track)
        assert row.source == FeatureSource.freqblog
        assert freq.calls == ["miss2"]
        assert report.features_from_freqblog == 1
        budget = session.exec(select(FreqBlogBudget)).one()
        assert budget.used == 1

    async def test_freqblog_hard_stops_at_budget_limit(self, session: Session) -> None:
        add_track(session, "m1")
        add_track(session, "m2")
        freq = FakeFreqBlog(by_id={"m1": features(), "m2": features()})
        svc = service(freqblog=freq, freqblog_budget_limit=1)

        report = await svc.run(session, batch_size=10)

        assert len(freq.calls) == 1  # second lookup refused before any request
        assert report.features_from_freqblog == 1
        assert report.features_missing == 1
        assert report.freqblog_exhausted is True

    async def test_total_miss_is_marked_missing_for_essentia(self, session: Session) -> None:
        track = add_track(session, "gone", isrc="ISRC404")
        svc = service()

        report = await svc.run(session, batch_size=10)

        row = stored_features(session, track)
        assert row.status == FeatureStatus.missing
        assert row.source is None
        assert row.energy is None
        assert report.features_missing == 1

    async def test_batch_size_bounds_the_pass(self, session: Session) -> None:
        for i in range(5):
            add_track(session, f"b{i}")
        svc = service(reccobeats=FakeRecco(by_id={f"b{i}": features() for i in range(5)}))

        report = await svc.run(session, batch_size=3)

        assert report.tracks_processed == 3
        rows = session.exec(select(TrackFeatures)).all()
        assert len(rows) == 3

    async def test_enriched_tracks_are_not_reprocessed(self, session: Session) -> None:
        add_track(session, "done")
        recco = FakeRecco(by_id={"done": features()})
        svc = service(reccobeats=recco)

        await svc.run(session, batch_size=10)
        report = await svc.run(session, batch_size=10)

        assert report.tracks_processed == 0
        assert len(recco.batch_calls) == 1  # second run had nothing to fetch

    async def test_calibration_recomputed_after_the_batch(self, session: Session) -> None:
        add_track(session, "c1")
        svc = service(reccobeats=FakeRecco(by_id={"c1": features(0.9)}))

        await svc.run(session, batch_size=10)

        row = session.exec(
            select(FeatureCalibration).where(FeatureCalibration.feature == "energy")
        ).one()
        assert row.p50 == pytest.approx(0.9)


class TestArtistEnrichment:
    async def test_lastfm_similarity_and_tags_persisted(self, session: Session) -> None:
        artist = add_artist(session, "a1", "Tycho")
        add_artist(session, "a2", "Boards of Canada")
        lastfm = FakeLastFm(
            similar={
                "Tycho": [
                    SimilarArtist(name="Boards of Canada", mbid="mbid-boc", match=0.9),
                    SimilarArtist(name="Unknown Act", match=0.5),
                ]
            },
            tags={"Tycho": [ArtistTagView(name="electronic", count=100)]},
        )
        svc = service(lastfm=lastfm)

        report = await svc.run(session, batch_size=10)

        edges = session.exec(
            select(ArtistSimilarity).where(ArtistSimilarity.artist_id == artist.id)
        ).all()
        assert len(edges) == 2
        by_name = {e.similar_artist_name: e for e in edges}
        # A similar artist we already track gets its catalog row linked.
        assert by_name["Boards of Canada"].similar_artist_id is not None
        assert by_name["Boards of Canada"].weight == pytest.approx(0.9)
        assert by_name["Boards of Canada"].source == SimilaritySource.lastfm
        assert by_name["Unknown Act"].similar_artist_id is None

        tags = session.exec(select(ArtistTag).where(ArtistTag.artist_id == artist.id)).all()
        assert len(tags) == 1
        assert tags[0].tag == "electronic"
        assert tags[0].source == TagSource.lastfm
        assert report.similarity_edges_added == 2
        assert report.tags_added == 1

    async def test_rerun_does_not_duplicate_edges_or_tags(self, session: Session) -> None:
        add_artist(session, "a1", "Tycho")
        lastfm = FakeLastFm(
            similar={"Tycho": [SimilarArtist(name="Aphex Twin", match=0.7)]},
            tags={"Tycho": [ArtistTagView(name="ambient", count=50)]},
        )
        svc = service(lastfm=lastfm)

        await svc.run(session, batch_size=10)
        await svc.run(session, batch_size=10)

        assert len(session.exec(select(ArtistSimilarity)).all()) == 1
        assert len(session.exec(select(ArtistTag)).all()) == 1

    async def test_without_lastfm_key_artist_enrichment_is_skipped(self, session: Session) -> None:
        add_artist(session, "a1", "Tycho")
        svc = service(lastfm=None)

        report = await svc.run(session, batch_size=10)

        assert session.exec(select(ArtistSimilarity)).all() == []
        assert report.lastfm_skipped is True

    async def test_mbid_resolved_via_track_isrc(self, session: Session) -> None:
        artist = add_artist(session, "a1", "Post Malone")
        add_track(
            session,
            "t1",
            isrc="USSM11912587",
            artists=[{"spotify_id": "a1", "name": "Post Malone"}],
        )
        mb = FakeMusicBrainz(
            by_isrc={
                "USSM11912587": IsrcRecording(
                    recording_mbid="rec-1",
                    artist_credits=[("Post Malone", "mbid-post-malone")],
                )
            }
        )
        svc = service(
            reccobeats=FakeRecco(by_id={"t1": features()}),
            musicbrainz=mb,
        )

        report = await svc.run(session, batch_size=10)

        session.refresh(artist)
        assert artist.mbid == "mbid-post-malone"
        assert report.artists_mbid_resolved == 1

    async def test_mbid_left_null_when_credits_do_not_match(self, session: Session) -> None:
        artist = add_artist(session, "a1", "Someone Else")
        add_track(
            session,
            "t1",
            isrc="USSM11912587",
            artists=[{"spotify_id": "a1", "name": "Someone Else"}],
        )
        mb = FakeMusicBrainz(
            by_isrc={
                "USSM11912587": IsrcRecording(
                    recording_mbid="rec-1",
                    artist_credits=[("Post Malone", "mbid-post-malone")],
                )
            }
        )
        svc = service(reccobeats=FakeRecco(by_id={"t1": features()}), musicbrainz=mb)

        await svc.run(session, batch_size=10)

        session.refresh(artist)
        assert artist.mbid is None
