"""Enrichment orchestrator: fallback ladder, budget, degradation, calibration."""

import httpx
import pytest
from sqlmodel import Session, select

from crate.model.enums import FeatureSource, FeatureStatus, SimilaritySource, TagSource
from crate.model.orm import (
    Artist,
    ArtistSimilarity,
    ArtistTag,
    FeatureCalibration,
    FreqBlogBudget,
    LocalDspCalibration,
    Track,
    TrackFeatures,
)
from crate.services.enrichment.localdsp import LocalAnalysis
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
        explode_on_isrc: set[str] | None = None,
    ) -> None:
        self.by_id = by_id or {}
        self.by_isrc = by_isrc or {}
        self.explode_on_isrc = explode_on_isrc or set()
        self.batch_calls: list[list[str]] = []
        self.isrc_calls: list[str] = []

    async def get_audio_features_batch(self, spotify_ids: list[str]) -> dict[str, AudioFeatures]:
        self.batch_calls.append(list(spotify_ids))
        return {i: self.by_id[i] for i in spotify_ids if i in self.by_id}

    async def get_audio_features_by_isrc(self, isrc: str) -> AudioFeatures | None:
        self.isrc_calls.append(isrc)
        if isrc in self.explode_on_isrc:
            raise httpx.ReadError("connection reset mid-read")
        return self.by_isrc.get(isrc)


class FakeFreqBlog:
    def __init__(
        self,
        by_id: dict[str, AudioFeatures] | None = None,
        explode_on: set[str] | None = None,
    ) -> None:
        self.by_id = by_id or {}
        self.explode_on = explode_on or set()
        self.calls: list[str] = []

    async def get_audio_features(self, spotify_id: str) -> AudioFeatures | None:
        self.calls.append(spotify_id)
        if spotify_id in self.explode_on:
            raise httpx.ReadError("connection reset mid-read")
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
    def __init__(
        self,
        by_isrc: dict[str, IsrcRecording] | None = None,
        explode_on: set[str] | None = None,
        status_error_on: set[str] | None = None,
    ) -> None:
        self.by_isrc = by_isrc or {}
        self.explode_on = explode_on or set()
        self.status_error_on = status_error_on or set()
        self.calls: list[str] = []

    async def lookup_isrc(self, isrc: str) -> IsrcRecording | None:
        self.calls.append(isrc)
        if isrc in self.explode_on:
            raise httpx.ReadError("connection reset mid-read")
        if isrc in self.status_error_on:
            request = httpx.Request("GET", f"https://musicbrainz.test/isrc/{isrc}")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError(
                "503 Service Unavailable", request=request, response=response
            )
        return self.by_isrc.get(isrc)


class FakeClock:
    """Manual monotonic clock — advance() is the only way time moves."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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


class FakeLocalDsp:
    """Raw local features by track title; None models a track with no preview."""

    def __init__(
        self,
        by_title: dict[str, dict[str, float]] | None = None,
        explode_on: set[str] | None = None,
    ) -> None:
        self.by_title = by_title or {}
        self.explode_on = explode_on or set()
        self.calls: list[str] = []

    async def analyze(self, title: str, artist: str) -> LocalAnalysis | None:
        self.calls.append(title)
        if title in self.explode_on:
            raise RuntimeError("decode failed")
        raw = self.by_title.get(title)
        if raw is None:
            return None
        return LocalAnalysis(features=dict(raw), preview_url=f"https://cdn.example/{title}")


def local_raw(energy: float = 0.5, tempo: float = 100.0) -> dict[str, float]:
    return {
        "tempo": tempo,
        "energy": energy,
        "danceability": 0.6,
        "valence": 0.4,
        "acousticness": 0.3,
        "instrumentalness": 0.7,
        "speechiness": 0.1,
        "liveness": 0.2,
        "loudness": -12.0,
    }


class TestLocalDspRung:
    async def test_localdsp_fills_a_track_every_remote_source_missed(
        self, session: Session
    ) -> None:
        track = add_track(session, "solo")  # no recco, no freqblog
        dsp = FakeLocalDsp(by_title={"t-solo": local_raw(energy=0.42)})
        svc = service(localdsp=dsp)

        report = await svc.run(session, batch_size=10)

        row = stored_features(session, track)
        assert row.status == FeatureStatus.present
        assert row.source == FeatureSource.essentia
        assert row.preview_resolved is True
        assert row.local_raw is not None
        assert row.local_raw["energy"] == pytest.approx(0.42)
        # No overlap set exists, so values are stored unmapped and flagged.
        assert row.energy == pytest.approx(0.42)
        assert row.key is None and row.mode is None
        assert report.features_from_localdsp == 1
        assert report.localdsp_uncalibrated is True
        assert report.localdsp_skipped is False

    async def test_no_preview_marks_the_row_and_is_not_retried(self, session: Session) -> None:
        track = add_track(session, "ghost")
        dsp = FakeLocalDsp()  # knows nothing -> no preview
        svc = service(localdsp=dsp)

        report = await svc.run(session, batch_size=10)
        row = stored_features(session, track)
        assert row.status == FeatureStatus.missing
        assert row.preview_resolved is False
        assert report.localdsp_no_preview == 1

        calls_after_first = len(dsp.calls)
        await svc.run(session, batch_size=10)
        assert len(dsp.calls) == calls_after_first  # not re-attempted

    async def test_values_are_quantile_mapped_via_the_overlap_set(self, session: Session) -> None:
        # Eight overlap tracks: ReccoBeats energy is local energy + 0.2.
        by_id = {}
        by_title = {}
        for i in range(8):
            add_track(session, f"o{i}")
            by_id[f"o{i}"] = features(energy=i / 10 + 0.2)
            by_title[f"t-o{i}"] = local_raw(energy=i / 10)
        target = add_track(session, "gap")
        by_title["t-gap"] = local_raw(energy=0.35)
        dsp = FakeLocalDsp(by_title=by_title)
        svc = service(reccobeats=FakeRecco(by_id=by_id), localdsp=dsp)

        report = await svc.run(session, batch_size=20)

        row = stored_features(session, target)
        assert row.source == FeatureSource.essentia
        # Local 0.35 lands in ReccoBeats space as 0.55 (the fitted +0.2 shift).
        assert row.energy == pytest.approx(0.55)
        assert row.local_raw is not None
        assert row.local_raw["energy"] == pytest.approx(0.35)
        assert report.localdsp_uncalibrated is False
        calibrations = session.exec(select(LocalDspCalibration)).all()
        assert {c.feature for c in calibrations} >= {"energy", "tempo"}
        # Overlap rows record that their previews resolved (and keep raw values).
        overlap_row = session.exec(
            select(TrackFeatures).join(Track).where(Track.spotify_id == "o0")
        ).one()
        assert overlap_row.preview_resolved is True
        assert overlap_row.source == FeatureSource.reccobeats  # source unchanged

    async def test_calibration_is_fitted_once_and_reused(self, session: Session) -> None:
        by_id = {f"o{i}": features(energy=i / 10 + 0.2) for i in range(8)}
        by_title = {f"t-o{i}": local_raw(energy=i / 10) for i in range(8)}
        for i in range(8):
            add_track(session, f"o{i}")
        by_title["t-gap1"] = local_raw(energy=0.3)
        by_title["t-gap2"] = local_raw(energy=0.4)
        add_track(session, "gap1")
        dsp = FakeLocalDsp(by_title=by_title)
        svc = service(reccobeats=FakeRecco(by_id=by_id), localdsp=dsp)
        await svc.run(session, batch_size=20)
        overlap_analyses = len(dsp.calls)

        add_track(session, "gap2")
        await svc.run(session, batch_size=20)

        # Second pass analyzed only the new gap track — no overlap refit.
        assert len(dsp.calls) == overlap_analyses + 1

    async def test_one_failing_analysis_does_not_void_the_pass(self, session: Session) -> None:
        first = add_track(session, "ok1")
        add_track(session, "boom")
        last = add_track(session, "ok2")
        dsp = FakeLocalDsp(
            by_title={"t-ok1": local_raw(0.1), "t-ok2": local_raw(0.9)},
            explode_on={"t-boom"},
        )
        svc = service(localdsp=dsp)

        report = await svc.run(session, batch_size=10)

        assert report.features_from_localdsp == 2
        assert stored_features(session, first).status == FeatureStatus.present
        assert stored_features(session, last).status == FeatureStatus.present
        assert len(report.errors) == 1 and "t-boom" in report.errors[0]

    async def test_without_localdsp_missing_rows_wait_untouched(self, session: Session) -> None:
        track = add_track(session, "waits")
        svc = service()  # no localdsp configured

        report = await svc.run(session, batch_size=10)

        row = stored_features(session, track)
        assert row.status == FeatureStatus.missing
        assert row.preview_resolved is None
        assert report.localdsp_skipped is True

    async def test_localdsp_features_enter_the_percentile_calibration(
        self, session: Session
    ) -> None:
        add_track(session, "solo")
        dsp = FakeLocalDsp(by_title={"t-solo": local_raw(energy=0.42)})
        svc = service(localdsp=dsp)

        await svc.run(session, batch_size=10)

        row = session.exec(
            select(FeatureCalibration).where(FeatureCalibration.feature == "energy")
        ).one()
        assert row.p50 == pytest.approx(0.42)


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

        report = await svc.run(session, batch_size=10, stage="all")

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

        await svc.run(session, batch_size=10, stage="all")
        await svc.run(session, batch_size=10, stage="all")

        assert len(session.exec(select(ArtistSimilarity)).all()) == 1
        assert len(session.exec(select(ArtistTag)).all()) == 1

    async def test_without_lastfm_key_artist_enrichment_is_skipped(self, session: Session) -> None:
        add_artist(session, "a1", "Tycho")
        svc = service(lastfm=None)

        report = await svc.run(session, batch_size=10, stage="all")

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

        report = await svc.run(session, batch_size=10, stage="all")

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

        await svc.run(session, batch_size=10, stage="all")

        session.refresh(artist)
        assert artist.mbid is None

    async def test_identity_examined_counts_artists_visited_even_when_none_resolve(
        self, session: Session
    ) -> None:
        # The live bug: an identity pass visits artists lacking MBIDs but
        # resolves none (their tracks have no MusicBrainz-matchable ISRC), so
        # artists_mbid_resolved stays 0. The grinder keyed "did work?" off the
        # resolved count alone and declared the stage drained after one pass —
        # while 18,700 artists still had no MBID. The report must carry a
        # key-independent "examined" count so the driver keeps grinding.
        add_artist(session, "a1", "Unmatched One")
        add_artist(session, "a2", "Unmatched Two")
        # No tracks / ISRCs → MusicBrainz is never even queried; nothing resolves.
        svc = service(musicbrainz=FakeMusicBrainz())

        report = await svc.run(session, batch_size=10, stage="identity")

        assert report.artists_mbid_resolved == 0
        assert report.artists_identity_examined == 2

    async def test_examined_artists_are_marked_and_not_reselected(self, session: Session) -> None:
        # The other half of the bug: without a "checked" marker the same
        # un-resolvable artists are re-selected every pass, so a driver that
        # kept grinding on artists_identity_examined would loop forever. Once
        # examined, an artist that did not resolve is marked and a second pass
        # examines nothing — the backlog genuinely drains.
        a1 = add_artist(session, "a1", "Unmatched One")
        add_artist(session, "a2", "Unmatched Two")
        svc = service(musicbrainz=FakeMusicBrainz())

        first = await svc.run(session, batch_size=10, stage="identity")
        assert first.artists_identity_examined == 2
        session.refresh(a1)
        assert a1.mbid_checked_at is not None  # examined-and-marked

        second = await svc.run(session, batch_size=10, stage="identity")
        assert second.artists_identity_examined == 0  # drained, no re-selection

    async def test_identity_examined_zero_when_all_artists_have_mbids(
        self, session: Session
    ) -> None:
        # Genuine drain: every artist already has an MBID → nothing examined →
        # the driver correctly stops.
        add_artist(session, "a1", "Known One", mbid="m1")
        add_artist(session, "a2", "Known Two", mbid="m2")
        svc = service(musicbrainz=FakeMusicBrainz())

        report = await svc.run(session, batch_size=10, stage="identity")

        assert report.artists_identity_examined == 0

    async def test_resolved_artists_do_not_need_the_checked_marker(self, session: Session) -> None:
        # An artist that resolves an MBID leaves the candidate set via mbid,
        # so it is not re-selected regardless of the marker.
        artist = add_artist(session, "a1", "Post Malone")
        add_track(session, "t1", isrc="US1", artists=[{"spotify_id": "a1", "name": "Post Malone"}])
        mb = FakeMusicBrainz(
            by_isrc={
                "US1": IsrcRecording(recording_mbid="r", artist_credits=[("Post Malone", "m")])
            }
        )
        svc = service(musicbrainz=mb)

        report = await svc.run(session, batch_size=10, stage="identity")

        session.refresh(artist)
        assert artist.mbid == "m"
        assert report.artists_mbid_resolved == 1
        # Second pass finds no un-MBID'd candidate.
        second = await svc.run(session, batch_size=10, stage="identity")
        assert second.artists_identity_examined == 0


class TestStageSelection:
    """MBID resolution is decoupled from the feature pass via the stage param."""

    async def test_default_feature_stage_skips_mbid_resolution(self, session: Session) -> None:
        artist = add_artist(session, "a1", "Post Malone")
        add_track(session, "t1", isrc="US1", artists=[{"spotify_id": "a1", "name": "Post Malone"}])
        mb = FakeMusicBrainz(
            by_isrc={
                "US1": IsrcRecording(recording_mbid="r", artist_credits=[("Post Malone", "m")])
            }
        )
        svc = service(reccobeats=FakeRecco(by_id={"t1": features()}), musicbrainz=mb)

        report = await svc.run(session, batch_size=10)  # default stage = feature

        session.refresh(artist)
        assert artist.mbid is None  # identity stage did not run
        assert mb.calls == []
        assert report.tracks_processed == 1  # feature work still happened

    async def test_identity_stage_resolves_mbids_without_touching_features(
        self, session: Session
    ) -> None:
        artist = add_artist(session, "a1", "Post Malone")
        add_track(session, "t1", isrc="US1", artists=[{"spotify_id": "a1", "name": "Post Malone"}])
        recco = FakeRecco(by_id={"t1": features()})
        mb = FakeMusicBrainz(
            by_isrc={
                "US1": IsrcRecording(recording_mbid="r", artist_credits=[("Post Malone", "m")])
            }
        )
        svc = service(reccobeats=recco, musicbrainz=mb)

        report = await svc.run(session, batch_size=10, stage="identity")

        session.refresh(artist)
        assert artist.mbid == "m"
        assert report.artists_mbid_resolved == 1
        # Feature pass was NOT run in identity stage.
        assert recco.batch_calls == []
        assert report.tracks_processed == 0
        # The feature row was never created — that is the feature stage's job.
        assert session.exec(select(TrackFeatures)).all() == []

    async def test_all_stage_runs_both(self, session: Session) -> None:
        artist = add_artist(session, "a1", "Post Malone")
        add_track(session, "t1", isrc="US1", artists=[{"spotify_id": "a1", "name": "Post Malone"}])
        recco = FakeRecco(by_id={"t1": features()})
        mb = FakeMusicBrainz(
            by_isrc={
                "US1": IsrcRecording(recording_mbid="r", artist_credits=[("Post Malone", "m")])
            }
        )
        svc = service(reccobeats=recco, musicbrainz=mb)

        report = await svc.run(session, batch_size=10, stage="all")

        session.refresh(artist)
        assert artist.mbid == "m"
        assert report.tracks_processed == 1
        assert recco.batch_calls != []


class TestTimeBudget:
    """A pass honours a wall-clock deadline and reports partial progress."""

    async def test_deadline_stops_the_feature_pass_between_tracks(self, session: Session) -> None:
        # Three misses that each fall through to the ISRC fallback; the fake
        # clock advances 100s per ISRC lookup, so a 150s budget clears exactly
        # one track then trips the deadline before the second.
        for i in range(3):
            add_track(session, f"m{i}", isrc=f"IS{i}")
        clock = FakeClock()

        class SlowRecco(FakeRecco):
            async def get_audio_features_by_isrc(self, isrc: str):
                clock.advance(100.0)
                return await super().get_audio_features_by_isrc(isrc)

        recco = SlowRecco(by_isrc={f"IS{i}": features() for i in range(3)})
        svc = service(reccobeats=recco)

        report = await svc.run(session, batch_size=10, time_budget_seconds=150.0, clock=clock)

        assert report.budget_exhausted is True
        # Only the tracks reached before the deadline were persisted.
        persisted = session.exec(select(TrackFeatures)).all()
        assert 1 <= len(persisted) < 3
        assert report.stage_seconds["isrc_fallback"] >= 100.0

    async def test_pass_within_budget_is_not_flagged(self, session: Session) -> None:
        add_track(session, "quick")
        clock = FakeClock()
        svc = service(reccobeats=FakeRecco(by_id={"quick": features()}))

        report = await svc.run(session, batch_size=10, time_budget_seconds=240.0, clock=clock)

        assert report.budget_exhausted is False
        assert report.tracks_processed == 1
        assert "reccobeats" in report.stage_seconds

    async def test_stage_seconds_records_per_stage_timing(self, session: Session) -> None:
        add_track(session, "t")
        clock = FakeClock()
        svc = service(reccobeats=FakeRecco(by_id={"t": features()}))

        report = await svc.run(session, batch_size=10, clock=clock)

        for key in ("reccobeats", "isrc_fallback", "localdsp", "musicbrainz"):
            assert key in report.stage_seconds


class TestTransientErrorIsolation:
    """A network read error on one track is recorded and skipped, never fatal."""

    async def test_isrc_read_error_skips_one_track(self, session: Session) -> None:
        ok = add_track(session, "ok", isrc="OK")
        bad = add_track(session, "bad", isrc="BAD")
        recco = FakeRecco(by_isrc={"OK": features(0.7)}, explode_on_isrc={"BAD"})
        svc = service(reccobeats=recco)

        report = await svc.run(session, batch_size=10)

        assert stored_features(session, ok).status == FeatureStatus.present
        # The exploding track ends missing, not crashing the pass.
        assert stored_features(session, bad).status == FeatureStatus.missing
        assert any("bad" in e.lower() for e in report.errors)

    async def test_mbid_read_error_skips_one_artist(self, session: Session) -> None:
        good = add_artist(session, "g", "Good Artist")
        bad = add_artist(session, "b", "Bad Artist")
        add_track(session, "tg", isrc="GISRC", artists=[{"spotify_id": "g", "name": "Good Artist"}])
        add_track(session, "tb", isrc="BISRC", artists=[{"spotify_id": "b", "name": "Bad Artist"}])
        mb = FakeMusicBrainz(
            by_isrc={
                "GISRC": IsrcRecording(recording_mbid="r", artist_credits=[("Good Artist", "gm")])
            },
            explode_on={"BISRC"},
        )
        svc = service(musicbrainz=mb)

        report = await svc.run(session, batch_size=10, stage="identity")

        session.refresh(good)
        session.refresh(bad)
        assert good.mbid == "gm"
        assert bad.mbid is None  # skipped, not fatal
        assert any("BISRC" in e or "Bad Artist" in e for e in report.errors)

    async def test_mbid_5xx_after_retries_skips_one_artist(self, session: Session) -> None:
        """A MusicBrainz 503 that survives client-side retries is a per-artist
        skip, not a pass-killing 500 (the failure that killed the overnight
        identity grind on 2026-07-16)."""
        good = add_artist(session, "g", "Good Artist")
        bad = add_artist(session, "b", "Bad Artist")
        add_track(session, "tg", isrc="GISRC", artists=[{"spotify_id": "g", "name": "Good Artist"}])
        add_track(session, "tb", isrc="BISRC", artists=[{"spotify_id": "b", "name": "Bad Artist"}])
        mb = FakeMusicBrainz(
            by_isrc={
                "GISRC": IsrcRecording(recording_mbid="r", artist_credits=[("Good Artist", "gm")])
            },
            status_error_on={"BISRC"},
        )
        svc = service(musicbrainz=mb)

        report = await svc.run(session, batch_size=10, stage="identity")

        session.refresh(good)
        session.refresh(bad)
        assert good.mbid == "gm"
        assert bad.mbid is None
        assert bad.mbid_checked_at is not None  # attempt is still marked
        assert any("503" in e for e in report.errors)
