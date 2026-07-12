"""Enrichment trigger and coverage status."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from crate.deps import CurrentUserDep, EnrichmentRunner, SessionDep, get_enrichment_runner
from crate.errors import AppError
from crate.model.enums import FeatureSource, FeatureStatus
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

# Enrichment pass slice. "feature" (the map's blocker) is the default and never
# waits behind the 1 req/s MusicBrainz "identity" work; "all" runs both.
EnrichmentStage = Literal["feature", "identity", "all"]

# Wall-clock budget bounds. No pass may run longer than the cap — a request that
# blocks for an hour is exactly the failure this replaces.
MAX_TIME_BUDGET_SECONDS = 600
DEFAULT_TIME_BUDGET_SECONDS = 240

# Single-flight guard: one active pass per user. A second concurrent run for the
# same user is refused with 409 rather than overlapping the in-flight one (the
# overlap that let the old grinder double-process the library). In-process only,
# which suffices for the single-instance deployment.
_active_passes: set[int] = set()


def mark_active(user_id: int) -> None:
    _active_passes.add(user_id)


def clear_active(user_id: int) -> None:
    _active_passes.discard(user_id)


def is_active(user_id: int) -> bool:
    return user_id in _active_passes


def reset_active_passes() -> None:
    """Clear the guard — for tests that need an order-independent starting state."""
    _active_passes.clear()


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
    features_from_localdsp: int = Field(
        description="Tracks resolved by analyzing their 30-second preview locally."
    )
    localdsp_no_preview: int = Field(
        description="Tracks local analysis wanted but no preview audio exists for."
    )
    features_missing: int = Field(
        description="Tracks that ended the pass without features from any source."
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
    localdsp_skipped: bool = Field(
        description="True when local audio analysis is disabled, so remote-missed "
        "tracks stayed queued."
    )
    localdsp_uncalibrated: bool = Field(
        description="True when locally-computed values were stored without "
        "cross-source calibration because too few tracks carry both a "
        "ReccoBeats value and a usable preview."
    )
    budget_exhausted: bool = Field(
        default=False,
        description="True when the pass hit its wall-clock budget before "
        "draining its work; the counts are honest partial progress and the "
        "next pass resumes where this one stopped.",
    )
    stage_seconds: dict[str, float] = Field(
        default_factory=dict,
        description="Wall-clock seconds spent in each stage this pass "
        "(reccobeats, isrc_fallback, localdsp, musicbrainz).",
    )
    errors: list[str] = Field(
        description="Per-track failures the pass survived (a bad download or "
        "decode skips that track, never the whole run)."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class FreqBlogBudgetStatus(BaseModel):
    """Consumption of the FreqBlog monthly lookup allowance."""

    configured: bool = Field(description="Whether a FreqBlog API key is set.")
    month: str = Field(description="Calendar month the counter covers.")
    used: int = Field(description="Lookups consumed this month.")
    limit: int = Field(description="Monthly allowance; lookups stop when reached.")


class LocalDspStatus(BaseModel):
    """Progress of local preview analysis over the remote-missed backlog."""

    enabled: bool = Field(description="Whether local audio analysis runs during passes.")
    analyzed: int = Field(description="Tracks whose features came from local analysis.")
    queued: int = Field(
        description="Remote-missed tracks not yet attempted — the local analysis backlog."
    )
    no_preview: int = Field(
        description="Tracks that stay missing because no preview audio exists for them."
    )
    preview_resolution_pct: float | None = Field(
        description="Share of preview lookups that found audio, 0-100; null "
        "before any lookup has run."
    )


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
    features_by_source: dict[str, int] = Field(
        description="Tracks with features, broken down by the source that supplied them."
    )
    lastfm: Literal["active", "pending"] = Field(
        description="pending while no Last.fm API key is configured — artist "
        "similarity and tags wait on one."
    )
    freqblog: FreqBlogBudgetStatus
    local_dsp: LocalDspStatus
    links: dict[str, HalLink] = Field(serialization_alias="_links")


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


@router.post(
    "/run",
    summary="Run an enrichment pass now",
    description=(
        "Walks tracks without audio features and artists without similarity "
        "data, querying ReccoBeats first, then the per-track ISRC fallback, "
        "then FreqBlog while its monthly allowance lasts, then local analysis "
        "of the track's 30-second preview. Only tracks every rung misses are "
        "recorded as missing. Feature calibration percentiles are refreshed "
        "at the end. The pass honours a wall-clock budget (default 240s, cap "
        "600s) and returns honest partial progress once it trips, so no run "
        "blocks unbounded. stage=feature (the default) skips the slow "
        "MusicBrainz identity work so feature coverage never waits behind it; "
        "stage=identity resolves artist identifiers and similarity; stage=all "
        "does both. A second run while one is already active for the same user "
        "is refused with 409 ENRICHMENT_PASS_ACTIVE."
    ),
)
async def trigger_enrichment(
    session: SessionDep,
    user: CurrentUserDep,
    runner: EnrichmentRunnerDep,
    batch_size: Annotated[
        int,
        Query(ge=1, le=1000, description="Maximum tracks (and artists) processed this pass."),
    ] = 100,
    stage: Annotated[
        EnrichmentStage,
        Query(
            description="Pipeline slice to run: feature (audio features, the "
            "default), identity (artist MBIDs + Last.fm similarity/tags), or all."
        ),
    ] = "feature",
    time_budget_seconds: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_TIME_BUDGET_SECONDS,
            description="Wall-clock budget for the pass; it returns partial "
            "progress once this trips.",
        ),
    ] = DEFAULT_TIME_BUDGET_SECONDS,
) -> EnrichmentRunResult:
    assert user.id is not None
    if is_active(user.id):
        raise AppError(
            409,
            "An enrichment pass is already running",
            detail="Wait for the active pass to finish before starting another.",
            error_code="ENRICHMENT_PASS_ACTIVE",
        )
    mark_active(user.id)
    try:
        report = await runner(
            session,
            batch_size,
            time_budget_seconds=float(time_budget_seconds),
            stage=stage,
        )
    finally:
        clear_active(user.id)
    return EnrichmentRunResult(
        tracks_processed=report.tracks_processed,
        features_from_reccobeats=report.features_from_reccobeats,
        features_from_isrc_fallback=report.features_from_isrc_fallback,
        features_from_freqblog=report.features_from_freqblog,
        features_from_localdsp=report.features_from_localdsp,
        localdsp_no_preview=report.localdsp_no_preview,
        features_missing=report.features_missing,
        artists_processed=report.artists_processed,
        artists_mbid_resolved=report.artists_mbid_resolved,
        similarity_edges_added=report.similarity_edges_added,
        tags_added=report.tags_added,
        lastfm_skipped=report.lastfm_skipped,
        freqblog_exhausted=report.freqblog_exhausted,
        localdsp_skipped=report.localdsp_skipped,
        localdsp_uncalibrated=report.localdsp_uncalibrated,
        budget_exhausted=report.budget_exhausted,
        stage_seconds=report.stage_seconds,
        errors=report.errors,
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
    features_by_source = {
        source.value: count(
            select(func.count())
            .select_from(TrackFeatures)
            .where(TrackFeatures.status == FeatureStatus.present)
            .where(TrackFeatures.source == source)
        )
        for source in FeatureSource
    }
    localdsp_queued = count(
        select(func.count())
        .select_from(TrackFeatures)
        .where(TrackFeatures.status == FeatureStatus.missing)
        .where(TrackFeatures.preview_resolved == None)  # noqa: E711 — SQL expression
    )
    previews_found = count(
        select(func.count())
        .select_from(TrackFeatures)
        .where(TrackFeatures.preview_resolved == True)  # noqa: E712 — SQL expression
    )
    previews_absent = count(
        select(func.count())
        .select_from(TrackFeatures)
        .where(TrackFeatures.preview_resolved == False)  # noqa: E712 — SQL expression
    )
    preview_attempts = previews_found + previews_absent
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
        features_by_source=features_by_source,
        lastfm="active" if settings.lastfm_api_key else "pending",
        freqblog=FreqBlogBudgetStatus(
            configured=settings.freqblog_api_key is not None,
            month=month,
            used=budget_row.used if budget_row else 0,
            limit=settings.freqblog_monthly_budget,
        ),
        local_dsp=LocalDspStatus(
            enabled=settings.localdsp_enabled,
            analyzed=features_by_source[FeatureSource.essentia.value],
            queued=localdsp_queued,
            no_preview=previews_absent,
            preview_resolution_pct=(
                _pct(previews_found, preview_attempts) if preview_attempts else None
            ),
        ),
        links={
            "self": HalLink(href="/v1/enrichment/status"),
            "run": HalLink(href="/v1/enrichment/run"),
        },
    )
