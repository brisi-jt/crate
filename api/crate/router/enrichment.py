"""Enrichment trigger and coverage status."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from crate.deps import CurrentUserDep, EnrichmentRunner, SessionDep, get_enrichment_runner
from crate.model.enums import FeatureStatus
from crate.model.orm import (
    Artist,
    ArtistSimilarity,
    ArtistTag,
    FreqBlogBudget,
    Track,
    TrackFeatures,
)
from crate.model.orm.base import utcnow
from crate.settings import get_settings

router = APIRouter(prefix="/v1/enrichment", tags=["enrichment"])

EnrichmentRunnerDep = Annotated[EnrichmentRunner, Depends(get_enrichment_runner)]


class HalLink(BaseModel):
    href: str


class EnrichmentRunResult(BaseModel):
    """Counts from one enrichment pass."""

    tracks_processed: int = Field(description="Tracks examined for audio features this pass.")
    features_from_reccobeats: int = Field(
        description="Tracks whose features came from the ReccoBeats batch lookup."
    )
    features_from_isrc_fallback: int = Field(
        description="Tracks resolved through the per-track ISRC fallback."
    )
    features_from_freqblog: int = Field(
        description="Tracks resolved through FreqBlog (counted against its monthly allowance)."
    )
    features_missing: int = Field(
        description="Tracks no source could resolve; queued for local audio analysis."
    )
    artists_processed: int = Field(description="Artists examined for similarity and tags.")
    artists_mbid_resolved: int = Field(
        description="Artists newly linked to a MusicBrainz identifier."
    )
    similarity_edges_added: int = Field(description="New artist-similarity edges stored.")
    tags_added: int = Field(description="New artist tags stored.")
    lastfm_skipped: bool = Field(
        description="True when no Last.fm API key is configured, so artist "
        "similarity and tags were not fetched."
    )
    freqblog_exhausted: bool = Field(
        description="True when the FreqBlog monthly allowance ran out during the pass."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class FreqBlogBudgetStatus(BaseModel):
    """Consumption of the FreqBlog monthly lookup allowance."""

    configured: bool = Field(description="Whether a FreqBlog API key is set.")
    month: str = Field(description="Calendar month the counter covers.")
    used: int = Field(description="Lookups consumed this month.")
    limit: int = Field(description="Monthly allowance; lookups stop when reached.")


class EnrichmentStatus(BaseModel):
    """Coverage of the enrichment pipeline across the synced library."""

    tracks_total: int = Field(description="Tracks in the catalog.")
    tracks_with_features: int = Field(description="Tracks with audio features stored.")
    tracks_missing_features: int = Field(
        description="Tracks every source missed; they wait for local audio analysis."
    )
    tracks_pending: int = Field(description="Tracks not yet attempted.")
    feature_coverage_pct: float = Field(
        description="Share of tracks with features, 0-100. Below 90 means the "
        "fallback sources are not enough and local analysis should be considered."
    )
    artists_total: int = Field(description="Artists in the catalog.")
    artists_with_mbid: int = Field(description="Artists linked to a MusicBrainz identifier.")
    artists_with_similarity: int = Field(description="Artists with at least one similar artist.")
    artists_with_tags: int = Field(description="Artists with at least one tag.")
    similarity_coverage_pct: float = Field(
        description="Share of artists with similarity edges, 0-100."
    )
    tag_coverage_pct: float = Field(description="Share of artists with tags, 0-100.")
    lastfm: Literal["active", "pending"] = Field(
        description="pending while no Last.fm API key is configured — artist "
        "similarity and tags wait on one."
    )
    freqblog: FreqBlogBudgetStatus
    links: dict[str, HalLink] = Field(serialization_alias="_links")


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


@router.post(
    "/run",
    summary="Run an enrichment pass now",
    description=(
        "Walks tracks without audio features and artists without similarity "
        "data, querying ReccoBeats first, then the per-track ISRC fallback, "
        "then FreqBlog while its monthly allowance lasts. Tracks that every "
        "source misses are recorded as missing. Feature calibration "
        "percentiles are refreshed at the end. Runs synchronously and returns "
        "the pass's counts."
    ),
)
async def trigger_enrichment(
    session: SessionDep,
    _user: CurrentUserDep,
    runner: EnrichmentRunnerDep,
    batch_size: Annotated[
        int,
        Query(ge=1, le=1000, description="Maximum tracks (and artists) processed this pass."),
    ] = 100,
) -> EnrichmentRunResult:
    report = await runner(session, batch_size)
    return EnrichmentRunResult(
        tracks_processed=report.tracks_processed,
        features_from_reccobeats=report.features_from_reccobeats,
        features_from_isrc_fallback=report.features_from_isrc_fallback,
        features_from_freqblog=report.features_from_freqblog,
        features_missing=report.features_missing,
        artists_processed=report.artists_processed,
        artists_mbid_resolved=report.artists_mbid_resolved,
        similarity_edges_added=report.similarity_edges_added,
        tags_added=report.tags_added,
        lastfm_skipped=report.lastfm_skipped,
        freqblog_exhausted=report.freqblog_exhausted,
        links={
            "status": HalLink(href="/v1/enrichment/status"),
            "self": HalLink(href="/v1/enrichment/run"),
        },
    )


@router.get(
    "/status",
    summary="Enrichment coverage",
    description=(
        "Feature, similarity, and tag coverage across the synced library, "
        "plus the FreqBlog allowance. feature_coverage_pct is the headline "
        "number: it decides whether the hosted sources suffice or local "
        "audio analysis is needed."
    ),
)
def enrichment_status(session: SessionDep, _user: CurrentUserDep) -> EnrichmentStatus:
    settings = get_settings()

    def count(statement) -> int:
        return session.exec(statement).one()

    tracks_total = count(select(func.count()).select_from(Track))
    tracks_with_features = count(
        select(func.count())
        .select_from(TrackFeatures)
        .where(TrackFeatures.status == FeatureStatus.present)
    )
    tracks_missing = count(
        select(func.count())
        .select_from(TrackFeatures)
        .where(TrackFeatures.status == FeatureStatus.missing)
    )
    artists_total = count(select(func.count()).select_from(Artist))
    artists_with_mbid = count(
        select(func.count()).select_from(Artist).where(Artist.mbid != None)  # noqa: E711
    )
    artists_with_similarity = count(
        select(func.count(func.distinct(ArtistSimilarity.artist_id))).select_from(ArtistSimilarity)
    )
    artists_with_tags = count(
        select(func.count(func.distinct(ArtistTag.artist_id))).select_from(ArtistTag)
    )

    month = utcnow().strftime("%Y-%m")
    budget_row = session.exec(select(FreqBlogBudget).where(FreqBlogBudget.month == month)).first()

    return EnrichmentStatus(
        tracks_total=tracks_total,
        tracks_with_features=tracks_with_features,
        tracks_missing_features=tracks_missing,
        tracks_pending=tracks_total - tracks_with_features - tracks_missing,
        feature_coverage_pct=_pct(tracks_with_features, tracks_total),
        artists_total=artists_total,
        artists_with_mbid=artists_with_mbid,
        artists_with_similarity=artists_with_similarity,
        artists_with_tags=artists_with_tags,
        similarity_coverage_pct=_pct(artists_with_similarity, artists_total),
        tag_coverage_pct=_pct(artists_with_tags, artists_total),
        lastfm="active" if settings.lastfm_api_key else "pending",
        freqblog=FreqBlogBudgetStatus(
            configured=settings.freqblog_api_key is not None,
            month=month,
            used=budget_row.used if budget_row else 0,
            limit=settings.freqblog_monthly_budget,
        ),
        links={
            "self": HalLink(href="/v1/enrichment/status"),
            "run": HalLink(href="/v1/enrichment/run"),
        },
    )
