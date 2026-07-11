"""Enrichment orchestrator.

One pass walks un-enriched tracks and artists, fans out to the sources with
a fallback ladder (ReccoBeats → ReccoBeats-by-ISRC → FreqBlog → marked
missing for later Essentia analysis), persists results, and refreshes the
feature calibration percentiles.
"""

from dataclasses import dataclass, field
from typing import Protocol

from sqlmodel import Session, select

from crate.model.enums import FeatureSource, FeatureStatus, SimilaritySource, TagSource
from crate.model.orm import Artist, ArtistSimilarity, ArtistTag, Track, TrackFeatures
from crate.model.orm.base import utcnow
from crate.services.analytics.snapshots import invalidate_snapshots
from crate.services.enrichment.calibration import recompute_calibration
from crate.services.enrichment.freqblog import try_consume_budget
from crate.services.enrichment.models import (
    ArtistTagView,
    AudioFeatures,
    IsrcRecording,
    SimilarArtist,
)

# ISRC lookups attempted per artist when resolving an MBID; each costs a
# paced MusicBrainz request, so the ladder stays short.
MAX_MBID_LOOKUPS_PER_ARTIST = 2


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


@dataclass
class EnrichmentReport:
    """Counts from one enrichment pass."""

    tracks_processed: int = 0
    features_from_reccobeats: int = 0
    features_from_isrc_fallback: int = 0
    features_from_freqblog: int = 0
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
        freqblog_budget_limit: int = 1000,
        month: str | None = None,
    ) -> None:
        self._reccobeats = reccobeats
        self._musicbrainz = musicbrainz
        self._freqblog = freqblog
        self._lastfm = lastfm
        self._freqblog_budget_limit = freqblog_budget_limit
        self._month = month

    async def run(self, session: Session, *, batch_size: int = 100) -> EnrichmentReport:
        report = EnrichmentReport(lastfm_skipped=self._lastfm is None)
        await self._enrich_track_features(session, batch_size, report)
        await self._resolve_artist_mbids(session, batch_size, report)
        if self._lastfm is not None:
            await self._enrich_artists_from_lastfm(session, batch_size, report)
        recompute_calibration(session)
        # New feature values shift the percentile space itself, so cached
        # analytics for every user are stale, not just one library's.
        if report.tracks_processed:
            invalidate_snapshots(session)
            session.commit()
        return report

    # -- track features -----------------------------------------------------

    async def _enrich_track_features(
        self, session: Session, batch_size: int, report: EnrichmentReport
    ) -> None:
        candidates = session.exec(
            select(Track)
            .join(TrackFeatures, TrackFeatures.track_id == Track.id, isouter=True)
            .where(TrackFeatures.id == None)  # noqa: E711 — SQL expression
            .limit(batch_size)
        ).all()
        if not candidates:
            return
        report.tracks_processed = len(candidates)

        batch = await self._reccobeats.get_audio_features_batch(
            [track.spotify_id for track in candidates]
        )
        month = self._month or utcnow().strftime("%Y-%m")

        for track in candidates:
            features = batch.get(track.spotify_id)
            if features is not None:
                report.features_from_reccobeats += 1
                source: FeatureSource | None = FeatureSource.reccobeats
            else:
                features, source = await self._feature_fallbacks(session, track, month, report)
            session.add(self._build_features_row(track, features, source, report))
        session.commit()

    async def _feature_fallbacks(
        self, session: Session, track: Track, month: str, report: EnrichmentReport
    ) -> tuple[AudioFeatures | None, FeatureSource | None]:
        if track.isrc:
            features = await self._reccobeats.get_audio_features_by_isrc(track.isrc)
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

    # -- artist mbids --------------------------------------------------------

    async def _resolve_artist_mbids(
        self, session: Session, batch_size: int, report: EnrichmentReport
    ) -> None:
        candidates = session.exec(
            select(Artist).where(Artist.mbid == None).limit(batch_size)  # noqa: E711
        ).all()
        if not candidates:
            return

        isrcs_by_artist = self._isrcs_by_artist_spotify_id(session)
        for artist in candidates:
            for isrc in isrcs_by_artist.get(artist.spotify_id, [])[:MAX_MBID_LOOKUPS_PER_ARTIST]:
                recording = await self._musicbrainz.lookup_isrc(isrc)
                if recording is None:
                    continue
                mbid = self._match_credit(artist.name, recording)
                if mbid is not None:
                    artist.mbid = mbid
                    session.add(artist)
                    report.artists_mbid_resolved += 1
                    break
        session.commit()

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
        self, session: Session, batch_size: int, report: EnrichmentReport
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
        report.artists_processed = len(candidates)

        artists_by_name = {row.name.lower(): row for row in session.exec(select(Artist)).all()}
        for artist in candidates:
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


async def run_enrichment(session: Session, batch_size: int) -> EnrichmentReport:
    """Production wiring: build clients from settings and run one pass."""
    from crate.services.enrichment.cache import ResponseCache
    from crate.services.enrichment.freqblog import FreqBlogClient
    from crate.services.enrichment.lastfm import LastFmClient
    from crate.services.enrichment.musicbrainz import MusicBrainzClient
    from crate.services.enrichment.reccobeats import ReccoBeatsClient
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
    clients = [c for c in (reccobeats, musicbrainz, freqblog, lastfm) if c is not None]
    try:
        service = EnrichmentService(
            reccobeats=reccobeats,
            musicbrainz=musicbrainz,
            freqblog=freqblog,
            lastfm=lastfm,
            freqblog_budget_limit=settings.freqblog_monthly_budget,
        )
        return await service.run(session, batch_size=batch_size)
    finally:
        for client in clients:
            await client.aclose()
