"""Enrichment orchestrator.

One pass walks un-enriched tracks and artists, fans out to the sources with
a fallback ladder (ReccoBeats → ReccoBeats-by-ISRC → FreqBlog → local audio
analysis of the track's preview → marked missing), persists results, and
refreshes the feature calibration percentiles.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx
from sqlmodel import Session, select

from crate.model.enums import FeatureSource, FeatureStatus, SimilaritySource, TagSource
from crate.model.orm import (
    Artist,
    ArtistSimilarity,
    ArtistTag,
    LocalDspCalibration,
    Track,
    TrackFeatures,
)
from crate.model.orm.base import utcnow
from crate.services.analytics.snapshots import invalidate_snapshots
from crate.services.enrichment.calibration import recompute_calibration
from crate.services.enrichment.freqblog import try_consume_budget
from crate.services.enrichment.localdsp import (
    LOCAL_FEATURES,
    MIN_OVERLAP_SAMPLES,
    OVERLAP_SAMPLE_LIMIT,
    LocalAnalysis,
    apply_quantile_map,
    fit_quantile_map,
)
from crate.services.enrichment.models import (
    ArtistTagView,
    AudioFeatures,
    IsrcRecording,
    SimilarArtist,
)

# ISRC lookups attempted per artist when resolving an MBID; each costs a
# paced MusicBrainz request, so the ladder stays short.
MAX_MBID_LOOKUPS_PER_ARTIST = 2

# Which slice of the pipeline one pass runs. "feature" is the map's blocker and
# the default — it must never wait behind 1 req/s MusicBrainz lookups, so MBID
# resolution lives in "identity". "all" runs both, for backfills that can spend
# a longer budget.
Stage = Literal["feature", "identity", "all"]

# Default wall-clock budget for a pass. Passes check the deadline between
# per-track (and per-artist) units and return partial progress once it trips,
# so no single request runs unbounded.
DEFAULT_TIME_BUDGET_SECONDS = 240.0

Clock = Callable[[], float]

# Transient network faults on a single unit (a read reset mid-stream, a
# connect/read timeout) are isolated per-track: recorded and skipped, never
# fatal to the pass. Programming errors are not swallowed.
_TRANSIENT_ERRORS = (httpx.TransportError, httpx.TimeoutException)


class _BudgetExhausted(Exception):
    """Raised internally to unwind a stage once its deadline trips."""


class _Deadline:
    """Wall-clock budget tracker with per-stage timing.

    ``check`` is called between per-track/artist units; it raises
    ``_BudgetExhausted`` once the clock passes the deadline. ``timed``
    attributes the elapsed wall-clock of a block to a named stage so the
    report can show where a pass spent its budget.
    """

    STAGES = ("reccobeats", "isrc_fallback", "localdsp", "musicbrainz")

    def __init__(self, clock: Clock, deadline: float) -> None:
        self._clock = clock
        self._deadline = deadline
        self.stage_seconds: dict[str, float] = dict.fromkeys(self.STAGES, 0.0)

    def expired(self) -> bool:
        return self._clock() >= self._deadline

    def check(self) -> None:
        if self.expired():
            raise _BudgetExhausted

    def add(self, stage: str, seconds: float) -> None:
        self.stage_seconds[stage] = self.stage_seconds.get(stage, 0.0) + seconds

    async def timed(self, stage: str, awaitable):
        """Await ``awaitable``, attributing its wall-clock to ``stage``."""
        start = self._clock()
        try:
            return await awaitable
        finally:
            self.add(stage, self._clock() - start)


def _primary_artist_name(track: Track) -> str:
    """First credited artist — what the Deezer preview search matches against."""
    for credited in track.artists:
        name = credited.get("name")
        if name:
            return str(name)
    return ""


class FeatureBatchSource(Protocol):
    async def get_audio_features_batch(
        self, spotify_ids: list[str]
    ) -> dict[str, AudioFeatures]: ...

    async def get_audio_features_by_isrc(self, isrc: str) -> AudioFeatures | None: ...


class FeatureFallbackSource(Protocol):
    async def get_audio_features(self, spotify_id: str) -> AudioFeatures | None: ...


class ArtistInfoSource(Protocol):
    async def get_similar_artists(self, artist_name: str) -> list[SimilarArtist]: ...

    async def get_artist_top_tags(self, artist_name: str) -> list[ArtistTagView]: ...


class MbidSource(Protocol):
    async def lookup_isrc(self, isrc: str) -> IsrcRecording | None: ...


class LocalDspSource(Protocol):
    async def analyze(self, title: str, artist: str) -> LocalAnalysis | None: ...


@dataclass
class EnrichmentReport:
    """Counts from one enrichment pass."""

    tracks_processed: int = 0
    features_from_reccobeats: int = 0
    features_from_isrc_fallback: int = 0
    features_from_freqblog: int = 0
    features_from_localdsp: int = 0
    # Tracks local analysis wanted but Deezer had no preview for.
    localdsp_no_preview: int = 0
    features_missing: int = 0
    artists_processed: int = 0
    artists_mbid_resolved: int = 0
    similarity_edges_added: int = 0
    tags_added: int = 0
    # True when no Last.fm API key is configured — artist similarity/tag
    # coverage stays pending until one is set.
    lastfm_skipped: bool = False
    # True when the FreqBlog monthly allowance ran out during the pass.
    freqblog_exhausted: bool = False
    # True when no local-analysis client is configured — remote-missed tracks
    # stay queued as missing.
    localdsp_skipped: bool = False
    # True when local values were stored raw because the overlap set was too
    # small to fit the quantile map into the ReccoBeats space.
    localdsp_uncalibrated: bool = False
    # True when the wall-clock budget tripped before the pass drained its work;
    # the counts above are honest partial progress, and another pass resumes.
    budget_exhausted: bool = False
    # Wall-clock seconds spent in each stage, so the grinder can see where a
    # pass's time went (reccobeats, isrc_fallback, localdsp, musicbrainz).
    stage_seconds: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


FEATURE_FIELDS = (
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "tempo",
    "key",
    "mode",
    "loudness",
)


class EnrichmentService:
    def __init__(
        self,
        *,
        reccobeats: FeatureBatchSource,
        musicbrainz: MbidSource,
        freqblog: FeatureFallbackSource | None = None,
        lastfm: ArtistInfoSource | None = None,
        localdsp: LocalDspSource | None = None,
        freqblog_budget_limit: int = 1000,
        month: str | None = None,
    ) -> None:
        self._reccobeats = reccobeats
        self._musicbrainz = musicbrainz
        self._freqblog = freqblog
        self._lastfm = lastfm
        self._localdsp = localdsp
        self._freqblog_budget_limit = freqblog_budget_limit
        self._month = month

    async def run(
        self,
        session: Session,
        *,
        batch_size: int = 100,
        time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
        stage: Stage = "feature",
        clock: Clock = time.monotonic,
    ) -> EnrichmentReport:
        report = EnrichmentReport(
            lastfm_skipped=self._lastfm is None,
            localdsp_skipped=self._localdsp is None,
        )
        deadline = _Deadline(clock, clock() + time_budget_seconds)
        run_feature = stage in ("feature", "all")
        run_identity = stage in ("identity", "all")

        try:
            if run_feature:
                await self._enrich_track_features(session, batch_size, report, deadline)
                if self._localdsp is not None:
                    await self._analyze_missing_locally(session, batch_size, report, deadline)
            if run_identity:
                await self._resolve_artist_mbids(session, batch_size, report, deadline)
                if self._lastfm is not None:
                    await self._enrich_artists_from_lastfm(session, batch_size, report, deadline)
        except _BudgetExhausted:
            report.budget_exhausted = True
            session.commit()

        report.stage_seconds = dict(deadline.stage_seconds)
        recompute_calibration(session)
        # New feature values shift the percentile space itself, so cached
        # analytics for every user are stale, not just one library's.
        if report.tracks_processed or report.features_from_localdsp:
            invalidate_snapshots(session)
            session.commit()
        return report

    # -- track features -----------------------------------------------------

    async def _enrich_track_features(
        self,
        session: Session,
        batch_size: int,
        report: EnrichmentReport,
        deadline: _Deadline,
    ) -> None:
        candidates = session.exec(
            select(Track)
            .join(TrackFeatures, TrackFeatures.track_id == Track.id, isouter=True)
            .where(TrackFeatures.id == None)  # noqa: E711 — SQL expression
            .limit(batch_size)
        ).all()
        if not candidates:
            return

        batch = await deadline.timed(
            "reccobeats",
            self._reccobeats.get_audio_features_batch([track.spotify_id for track in candidates]),
        )
        month = self._month or utcnow().strftime("%Y-%m")

        for track in candidates:
            deadline.check()  # honour the budget between per-track units
            features = batch.get(track.spotify_id)
            if features is not None:
                report.features_from_reccobeats += 1
                source: FeatureSource | None = FeatureSource.reccobeats
            else:
                try:
                    features, source = await self._feature_fallbacks(
                        session, track, month, report, deadline
                    )
                except _TRANSIENT_ERRORS as exc:  # one bad read never voids the pass
                    report.errors.append(f"features {track.name}: {exc!r}")
                    features, source = None, None
            session.add(self._build_features_row(track, features, source, report))
            report.tracks_processed += 1
        session.commit()

    async def _feature_fallbacks(
        self,
        session: Session,
        track: Track,
        month: str,
        report: EnrichmentReport,
        deadline: _Deadline,
    ) -> tuple[AudioFeatures | None, FeatureSource | None]:
        if track.isrc:
            features = await deadline.timed(
                "isrc_fallback", self._reccobeats.get_audio_features_by_isrc(track.isrc)
            )
            if features is not None:
                report.features_from_isrc_fallback += 1
                return features, FeatureSource.reccobeats
        if self._freqblog is not None:
            if not try_consume_budget(session, month=month, limit=self._freqblog_budget_limit):
                report.freqblog_exhausted = True
                return None, None
            features = await self._freqblog.get_audio_features(track.spotify_id)
            if features is not None:
                report.features_from_freqblog += 1
                return features, FeatureSource.freqblog
        return None, None

    @staticmethod
    def _build_features_row(
        track: Track,
        features: AudioFeatures | None,
        source: FeatureSource | None,
        report: EnrichmentReport,
    ) -> TrackFeatures:
        if features is None or source is None:
            report.features_missing += 1
            return TrackFeatures(track_id=track.id, status=FeatureStatus.missing, source=None)
        values = {name: getattr(features, name) for name in FEATURE_FIELDS}
        return TrackFeatures(
            track_id=track.id, status=FeatureStatus.present, source=source, **values
        )

    # -- local audio analysis -------------------------------------------------

    async def _analyze_missing_locally(
        self,
        session: Session,
        batch_size: int,
        report: EnrichmentReport,
        deadline: _Deadline,
    ) -> None:
        """Final rung: analyze the Deezer previews of remote-missed tracks.

        Serves both rows marked missing earlier this pass and the standing
        backlog. Rows whose preview lookup already failed (preview_resolved
        False) are left alone — Deezer will not grow a preview between passes.
        """
        assert self._localdsp is not None
        rows = session.exec(
            select(TrackFeatures, Track)
            .join(Track, Track.id == TrackFeatures.track_id)
            .where(TrackFeatures.status == FeatureStatus.missing)
            .where(TrackFeatures.preview_resolved == None)  # noqa: E711 — SQL expression
            .limit(batch_size)
        ).all()
        if not rows:
            return
        maps = await self._ensure_localdsp_calibration(session, report)

        for features_row, track in rows:
            deadline.check()  # honour the budget between per-track units
            try:
                analysis = await deadline.timed(
                    "localdsp",
                    self._localdsp.analyze(track.name, _primary_artist_name(track)),
                )
            except Exception as exc:  # one bad preview never voids the pass
                report.errors.append(f"localdsp {track.name}: {exc}")
                continue
            if analysis is None:
                features_row.preview_resolved = False
                report.localdsp_no_preview += 1
                session.add(features_row)
                continue
            raw = analysis.features
            for feature in LOCAL_FEATURES:
                value = raw.get(feature)
                if value is None:
                    continue
                anchors = maps.get(feature)
                mapped = apply_quantile_map(*anchors, value) if anchors else value
                setattr(features_row, feature, mapped)
            features_row.status = FeatureStatus.present
            features_row.source = FeatureSource.essentia
            features_row.local_raw = raw
            features_row.preview_resolved = True
            session.add(features_row)
            report.features_from_localdsp += 1
            # The track ends the pass with features after all.
            report.features_missing = max(0, report.features_missing - 1)
        session.commit()

    async def _ensure_localdsp_calibration(
        self, session: Session, report: EnrichmentReport
    ) -> dict[str, tuple[list[float], list[float]]]:
        """Per-feature quantile maps into the ReccoBeats space, fitting on demand.

        Fitting analyzes the previews of tracks that already carry ReccoBeats
        values (the overlap set), pairing each feature's local and remote
        value. Persisted once; later passes just load the stored anchors.
        """
        assert self._localdsp is not None
        existing = session.exec(select(LocalDspCalibration)).all()
        if existing:
            return {row.feature: (row.local_anchors, row.target_anchors) for row in existing}

        overlap = session.exec(
            select(TrackFeatures, Track)
            .join(Track, Track.id == TrackFeatures.track_id)
            .where(TrackFeatures.status == FeatureStatus.present)
            .where(TrackFeatures.source == FeatureSource.reccobeats)
            .limit(OVERLAP_SAMPLE_LIMIT)
        ).all()

        pairs: dict[str, list[tuple[float, float]]] = {f: [] for f in LOCAL_FEATURES}
        analyzed = 0
        for recco_row, track in overlap:
            try:
                analysis = await self._localdsp.analyze(track.name, _primary_artist_name(track))
            except Exception as exc:
                report.errors.append(f"localdsp calibration {track.name}: {exc}")
                continue
            if analysis is None:
                if recco_row.preview_resolved is None:
                    recco_row.preview_resolved = False
                    session.add(recco_row)
                continue
            analyzed += 1
            # Keep what was learned: the preview exists and the raw values can
            # feed a future refit. source stays reccobeats.
            recco_row.preview_resolved = True
            recco_row.local_raw = analysis.features
            session.add(recco_row)
            for feature in LOCAL_FEATURES:
                target = getattr(recco_row, feature)
                local = analysis.features.get(feature)
                if target is not None and local is not None:
                    pairs[feature].append((local, target))

        if analyzed < MIN_OVERLAP_SAMPLES:
            report.localdsp_uncalibrated = True
            session.commit()
            return {}

        maps: dict[str, tuple[list[float], list[float]]] = {}
        for feature, samples in pairs.items():
            if len(samples) < MIN_OVERLAP_SAMPLES:
                continue
            local_anchors, target_anchors = fit_quantile_map(
                [s[0] for s in samples], [s[1] for s in samples]
            )
            session.add(
                LocalDspCalibration(
                    feature=feature,
                    local_anchors=local_anchors,
                    target_anchors=target_anchors,
                    sample_size=len(samples),
                )
            )
            maps[feature] = (local_anchors, target_anchors)
        session.commit()
        return maps

    # -- artist mbids --------------------------------------------------------

    async def _resolve_artist_mbids(
        self,
        session: Session,
        batch_size: int,
        report: EnrichmentReport,
        deadline: _Deadline,
    ) -> None:
        candidates = session.exec(
            select(Artist).where(Artist.mbid == None).limit(batch_size)  # noqa: E711
        ).all()
        if not candidates:
            return

        isrcs_by_artist = self._isrcs_by_artist_spotify_id(session)
        for artist in candidates:
            deadline.check()  # honour the budget between per-artist units
            try:
                await self._resolve_one_artist_mbid(
                    session, artist, isrcs_by_artist, report, deadline
                )
            except _TRANSIENT_ERRORS as exc:  # one bad read never voids the pass
                report.errors.append(f"musicbrainz {artist.name}: {exc!r}")
        session.commit()

    async def _resolve_one_artist_mbid(
        self,
        session: Session,
        artist: Artist,
        isrcs_by_artist: dict[str, list[str]],
        report: EnrichmentReport,
        deadline: _Deadline,
    ) -> None:
        for isrc in isrcs_by_artist.get(artist.spotify_id, [])[:MAX_MBID_LOOKUPS_PER_ARTIST]:
            recording = await deadline.timed("musicbrainz", self._musicbrainz.lookup_isrc(isrc))
            if recording is None:
                continue
            mbid = self._match_credit(artist.name, recording)
            if mbid is not None:
                artist.mbid = mbid
                session.add(artist)
                report.artists_mbid_resolved += 1
                break

    @staticmethod
    def _isrcs_by_artist_spotify_id(session: Session) -> dict[str, list[str]]:
        tracks = session.exec(select(Track).where(Track.isrc != None)).all()  # noqa: E711
        mapping: dict[str, list[str]] = {}
        for track in tracks:
            for credited in track.artists:
                spotify_id = credited.get("spotify_id")
                if spotify_id and track.isrc:
                    mapping.setdefault(spotify_id, []).append(track.isrc)
        return mapping

    @staticmethod
    def _match_credit(artist_name: str, recording: IsrcRecording) -> str | None:
        wanted = artist_name.strip().lower()
        for name, mbid in recording.artist_credits:
            if name.strip().lower() == wanted:
                return mbid
        return None

    # -- artist similarity + tags ---------------------------------------------

    async def _enrich_artists_from_lastfm(
        self,
        session: Session,
        batch_size: int,
        report: EnrichmentReport,
        deadline: _Deadline,
    ) -> None:
        assert self._lastfm is not None
        candidates = session.exec(
            select(Artist)
            .join(ArtistSimilarity, ArtistSimilarity.artist_id == Artist.id, isouter=True)
            .where(ArtistSimilarity.id == None)  # noqa: E711
            .limit(batch_size)
        ).all()
        if not candidates:
            return

        artists_by_name = {row.name.lower(): row for row in session.exec(select(Artist)).all()}
        for artist in candidates:
            deadline.check()  # honour the budget between per-artist units
            report.artists_processed += 1
            similar = await self._lastfm.get_similar_artists(artist.name)
            for entry in similar:
                if self._similarity_exists(session, artist, entry.name):
                    continue
                linked = artists_by_name.get(entry.name.lower())
                session.add(
                    ArtistSimilarity(
                        artist_id=artist.id,
                        similar_artist_id=linked.id if linked else None,
                        similar_artist_name=entry.name,
                        similar_artist_mbid=entry.mbid,
                        weight=entry.match,
                        source=SimilaritySource.lastfm,
                    )
                )
                report.similarity_edges_added += 1

            tags = await self._lastfm.get_artist_top_tags(artist.name)
            for tag in tags:
                if self._tag_exists(session, artist, tag.name):
                    continue
                session.add(
                    ArtistTag(
                        artist_id=artist.id,
                        tag=tag.name,
                        weight=tag.count,
                        source=TagSource.lastfm,
                    )
                )
                report.tags_added += 1
        session.commit()

    @staticmethod
    def _similarity_exists(session: Session, artist: Artist, similar_name: str) -> bool:
        return (
            session.exec(
                select(ArtistSimilarity)
                .where(ArtistSimilarity.artist_id == artist.id)
                .where(ArtistSimilarity.similar_artist_name == similar_name)
                .where(ArtistSimilarity.source == SimilaritySource.lastfm)
            ).first()
            is not None
        )

    @staticmethod
    def _tag_exists(session: Session, artist: Artist, tag: str) -> bool:
        return (
            session.exec(
                select(ArtistTag)
                .where(ArtistTag.artist_id == artist.id)
                .where(ArtistTag.tag == tag)
                .where(ArtistTag.source == TagSource.lastfm)
            ).first()
            is not None
        )


async def run_enrichment(
    session: Session,
    batch_size: int,
    *,
    time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
    stage: Stage = "feature",
) -> EnrichmentReport:
    """Production wiring: build clients from settings and run one budgeted pass."""
    from pathlib import Path

    from crate.services.enrichment.cache import ResponseCache
    from crate.services.enrichment.deezer import DeezerClient
    from crate.services.enrichment.freqblog import FreqBlogClient
    from crate.services.enrichment.lastfm import LastFmClient
    from crate.services.enrichment.localdsp import (
        DEEZER_PREVIEW_MIN_INTERVAL,
        LocalDspClient,
        PreviewCache,
        default_cache_dir,
    )
    from crate.services.enrichment.musicbrainz import MusicBrainzClient
    from crate.services.enrichment.reccobeats import ReccoBeatsClient
    from crate.services.enrichment.throttle import RateLimiter
    from crate.settings import get_settings

    settings = get_settings()
    reccobeats = ReccoBeatsClient(cache=ResponseCache(session, source="reccobeats"))
    musicbrainz = MusicBrainzClient(cache=ResponseCache(session, source="musicbrainz"))
    freqblog = (
        FreqBlogClient(
            api_key=settings.freqblog_api_key,
            cache=ResponseCache(session, source="freqblog"),
        )
        if settings.freqblog_api_key
        else None
    )
    lastfm = (
        LastFmClient(
            api_key=settings.lastfm_api_key,
            cache=ResponseCache(session, source="lastfm"),
        )
        if settings.lastfm_api_key
        else None
    )
    localdsp = None
    deezer = None
    if settings.localdsp_enabled:
        deezer = DeezerClient(
            cache=ResponseCache(session, source="deezer"),
            limiter=RateLimiter(min_interval=DEEZER_PREVIEW_MIN_INTERVAL),
        )
        if settings.localdsp_cache_dir:
            cache_dir = Path(settings.localdsp_cache_dir)
        else:
            cache_dir = default_cache_dir()
        localdsp = LocalDspClient(
            previews=deezer,
            cache=PreviewCache(cache_dir, max_bytes=settings.localdsp_cache_max_mb * 1024 * 1024),
        )
    clients = [c for c in (reccobeats, musicbrainz, freqblog, lastfm, deezer, localdsp) if c]
    try:
        service = EnrichmentService(
            reccobeats=reccobeats,
            musicbrainz=musicbrainz,
            freqblog=freqblog,
            lastfm=lastfm,
            localdsp=localdsp,
            freqblog_budget_limit=settings.freqblog_monthly_budget,
        )
        return await service.run(
            session,
            batch_size=batch_size,
            time_budget_seconds=time_budget_seconds,
            stage=stage,
        )
    finally:
        for client in clients:
            await client.aclose()
