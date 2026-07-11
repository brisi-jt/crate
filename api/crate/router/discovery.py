"""Discovery endpoints: the suggestion queue, review feedback, and batch runs.

The queue serves resolved candidates ranked by fit against the playlist's
sound. Accepting a suggestion routes through the standard journaled write
path, so a deck decision is as undoable as any other playlist edit.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import func, select

from crate.deps import (
    CurrentUserDep,
    DiscoveryRunner,
    SessionDep,
    WriterFactoryDep,
    get_discovery_runner,
)
from crate.errors import AppError, ProblemDetail
from crate.model.enums import (
    CandidateSource,
    CandidateStatus,
    FeedbackAction,
    MutationStatus,
    SnapshotKind,
)
from crate.model.orm import DiscoveryCandidate, Genre, Playlist
from crate.router.playlists import HalLink
from crate.services.analytics.snapshots import get_or_compute
from crate.services.discovery.frontier import compute_frontier_payload
from crate.services.discovery.generation import DEFAULT_CANDIDATE_LIMIT
from crate.services.discovery.service import (
    QueueEntry,
    accept_candidate,
    build_suggestion_queue,
    record_feedback,
)

router = APIRouter(tags=["discovery"])


# ------------------------------------------------------------------ bodies


class FeedbackBody(BaseModel):
    action: FeedbackAction = Field(
        description="accept adds the track to the playlist (journaled, undoable); "
        "reject removes it from every future queue; skip records the pass "
        "and keeps it available."
    )


class DiscoveryRunBody(BaseModel):
    playlist_id: int | None = Field(
        default=None,
        description="Restrict the pass to one playlist; omit to run every synced playlist.",
    )
    limit: int = Field(
        default=DEFAULT_CANDIDATE_LIMIT,
        ge=1,
        le=200,
        description="Maximum new candidates admitted per playlist.",
    )
    genre_seed: str | None = Field(
        default=None,
        description="Seed the pass from a genre instead of the playlist's own "
        "sound: candidates come from the genre's defining artists that the "
        "library lacks (see the frontier endpoint). Requires playlist_id.",
    )


# ---------------------------------------------------------------- responses


class FitBreakdownResource(BaseModel):
    """How a suggestion's fit score decomposes."""

    proximity: float = Field(
        description="Closeness to the playlist's acoustic centroid (1 = identical sound)."
    )
    affinity: float = Field(
        description="Strongest listener-similarity link from a playlist artist, 0..1."
    )
    novelty: float = Field(description="Penalty applied for artists already suggested many times.")
    feedback: float = Field(
        description="Shift from the artist's accept/reject history (positive = liked)."
    )
    fit: float = Field(description="The combined 0..1 score the queue is ordered by.")


class FingerprintPoint(BaseModel):
    """One feature compared between the candidate and the playlist."""

    feature: str
    candidate: float = Field(description="Candidate's library percentile, 0..1.")
    playlist: float = Field(description="Playlist centroid percentile, 0..1.")


class SuggestionResource(BaseModel):
    """One ranked entry in a playlist's suggestion queue."""

    id: int
    title: str
    artist: str
    album_name: str | None
    duration_ms: int | None
    source: CandidateSource = Field(description="Which pipeline proposed the track.")
    seed_artist: str | None = Field(
        description="The library artist whose similarity led here, when Last.fm-sourced."
    )
    spotify_id: str | None
    preview_url: str | None = Field(
        description="30-second audio preview; null when no preview could be found."
    )
    fit: float
    breakdown: FitBreakdownResource
    fingerprint: list[FingerprintPoint]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class SuggestionQueueResource(BaseModel):
    """A playlist's review queue, best fit first."""

    playlist_id: int
    playlist_name: str
    total: int
    items: list[SuggestionResource]
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class FeedbackResult(BaseModel):
    """Outcome of a review decision."""

    candidate_id: int
    action: FeedbackAction
    status: CandidateStatus = Field(description="The candidate's lifecycle state afterwards.")
    journal_id: int | None = Field(
        description="Set on accept: the journal entry for the playlist add (undo target)."
    )
    mutation_status: MutationStatus | None = Field(
        description="Set on accept: outcome of the playlist write."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class DiscoveryRunResult(BaseModel):
    """Counts from one discovery pass."""

    playlists_processed: int
    generated_lastfm: int
    generated_reccobeats: int
    generated_enao: int = Field(
        description="Candidates sourced from a genre seed's exemplar artists."
    )
    excluded: int = Field(
        description="Proposals dropped because they were already in the library, "
        "previously rejected, or already queued."
    )
    resolved: int
    unresolvable: int
    features_fetched: int
    previews_resolved: int
    lastfm_skipped: bool = Field(
        description="True when no Last.fm API key is configured — the pass ran "
        "on recommendations only."
    )
    errors: list[str] = Field(
        description="Per-step failures the pass survived (a source outage "
        "skips that step, never the whole run)."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ----------------------------------------------------------------- frontier


class TerritoryGenreResource(BaseModel):
    """One genre the library already inhabits."""

    genre_id: int
    name: str
    enao_rank: int | None = Field(
        description="Position in the global genre popularity ordering (1 = most popular)."
    )
    presence: float = Field(
        description="How strongly the library holds this genre, relative to "
        "its strongest genre (0..1)."
    )
    matched_artists: int = Field(description="Library artists counted toward the presence.")


class FrontierExemplarResource(BaseModel):
    """An artist that defines a frontier genre but isn't in the library."""

    name: str
    weight: float = Field(
        description="How central the artist is to the genre, 0..1 (1 = its strongest member)."
    )


class FrontierGenreResource(BaseModel):
    """A genre next door to the library's territory, worth exploring."""

    genre_id: int
    name: str
    enao_rank: int | None
    score: float = Field(
        description="Exploration score: adjacency to the library's territory, "
        "discounted by how much of the genre it already holds."
    )
    presence: float = Field(description="The library's existing hold on this genre, 0..1.")
    adjacent_to: list[str] = Field(
        description="The territory genres this one borders, strongest link first."
    )
    exemplars: list[FrontierExemplarResource] = Field(
        description="Defining artists not yet in the library — discovery seeds."
    )


class FrontierCoverage(BaseModel):
    library_artists: int = Field(description="Distinct credited artists in the scope.")
    matched_artists: int = Field(
        description="Of those, how many the genre atlas recognizes by name."
    )


class FrontierResponse(BaseModel):
    """Where the library lives in genre space, and what borders it."""

    territory: list[TerritoryGenreResource] = Field(
        description="Genres the library already inhabits, strongest first."
    )
    frontier: list[FrontierGenreResource] = Field(
        description="Adjacent but under-explored genres, best exploration "
        "score first. Each carries seed artists for a discovery run."
    )
    coverage: FrontierCoverage
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ------------------------------------------------------------------ helpers


def _require_playlist(session: SessionDep, user_id: int, playlist_id: int) -> Playlist:
    playlist = session.exec(
        select(Playlist)
        .where(Playlist.id == playlist_id)
        .where(Playlist.user_id == user_id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).first()
    if playlist is None:
        raise AppError(
            404,
            "Playlist not found",
            detail=f"No playlist with id {playlist_id}.",
            error_code="PLAYLIST_NOT_FOUND",
        )
    return playlist


def _suggestion_resource(entry: QueueEntry) -> SuggestionResource:
    candidate = entry.candidate
    assert candidate.id is not None
    links = {
        "feedback": HalLink(href=f"/v1/suggestions/{candidate.id}/feedback"),
        "playlist": HalLink(href=f"/v1/playlists/{candidate.playlist_id}"),
    }
    if candidate.spotify_id and not candidate.spotify_id.startswith("fake-"):
        links["spotify"] = HalLink(href=f"https://open.spotify.com/track/{candidate.spotify_id}")
    breakdown = entry.breakdown.as_dict()
    return SuggestionResource(
        id=candidate.id,
        title=candidate.title,
        artist=candidate.artist,
        album_name=candidate.album_name,
        duration_ms=candidate.duration_ms,
        source=candidate.source,
        seed_artist=candidate.seed_artist,
        spotify_id=candidate.spotify_id,
        preview_url=candidate.preview_url,
        fit=breakdown["fit"],
        breakdown=FitBreakdownResource.model_validate(breakdown),
        fingerprint=[FingerprintPoint.model_validate(point) for point in entry.fingerprint],
        links=links,
    )


# ----------------------------------------------------------------- endpoints


@router.get(
    "/v1/playlists/{playlist_id}/suggestions",
    summary="A playlist's suggestion queue",
    description=(
        "Discovered tracks ranked by how well they fit the playlist's sound. "
        "Each entry carries a fit breakdown, a per-feature comparison against "
        "the playlist profile, and a 30-second preview URL when one exists. "
        "Empty until a discovery run has generated candidates."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown playlist."}},
)
def get_suggestions(
    playlist_id: int,
    session: SessionDep,
    user: CurrentUserDep,
) -> SuggestionQueueResource:
    assert user.id is not None
    playlist = _require_playlist(session, user.id, playlist_id)
    queue = build_suggestion_queue(session, user, playlist)
    return SuggestionQueueResource(
        playlist_id=playlist_id,
        playlist_name=playlist.name,
        total=len(queue),
        items=[_suggestion_resource(entry) for entry in queue],
        links={
            "self": HalLink(href=f"/v1/playlists/{playlist_id}/suggestions"),
            "playlist": HalLink(href=f"/v1/playlists/{playlist_id}"),
            "run": HalLink(href="/v1/discovery/run"),
        },
    )


@router.post(
    "/v1/suggestions/{candidate_id}/feedback",
    summary="Review a suggestion",
    description=(
        "Records the decision and updates the queue. Accept adds the track "
        "to the playlist through the journaled write path — the response's "
        "journal link undoes it like any other edit. Reject bars the track "
        "from every future queue; skip just records the pass."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown suggestion."},
        409: {
            "model": ProblemDetail,
            "description": "The suggestion has already been reviewed or never resolved.",
        },
        502: {
            "model": ProblemDetail,
            "description": "Spotify rejected the add; the journal records the previous state.",
        },
    },
)
async def post_feedback(
    candidate_id: int,
    body: FeedbackBody,
    session: SessionDep,
    user: CurrentUserDep,
    writer_factory: WriterFactoryDep,
) -> FeedbackResult:
    candidate = session.get(DiscoveryCandidate, candidate_id)
    if candidate is None or candidate.user_id != user.id:
        raise AppError(
            404,
            "Suggestion not found",
            detail=f"No suggestion with id {candidate_id}.",
            error_code="SUGGESTION_NOT_FOUND",
        )
    if candidate.status != CandidateStatus.resolved:
        raise AppError(
            409,
            "Suggestion not reviewable",
            detail=f"Suggestion {candidate_id} is {candidate.status.value} — only "
            "resolved suggestions take feedback.",
            error_code="SUGGESTION_NOT_REVIEWABLE",
        )

    links: dict[str, HalLink] = {
        "queue": HalLink(href=f"/v1/playlists/{candidate.playlist_id}/suggestions"),
    }
    journal_id: int | None = None
    mutation_status: MutationStatus | None = None
    if body.action == FeedbackAction.accept:
        async with writer_factory(session, user) as writer:
            _, journal_id = await accept_candidate(session, user, candidate, writer)
        mutation_status = MutationStatus.applied
        links["journal"] = HalLink(href=f"/v1/journal/{journal_id}")
        links["undo"] = HalLink(href=f"/v1/journal/{journal_id}/undo")
        links["playlist"] = HalLink(href=f"/v1/playlists/{candidate.playlist_id}")
    else:
        record_feedback(session, user, candidate, body.action)

    return FeedbackResult(
        candidate_id=candidate_id,
        action=body.action,
        status=candidate.status,
        journal_id=journal_id,
        mutation_status=mutation_status,
        links=links,
    )


@router.get(
    "/v1/discovery/frontier",
    summary="Genre frontier",
    description=(
        "Maps the library onto the genre atlas: the territory it already "
        "inhabits, and the frontier — genres that border that territory "
        "through shared artists but are barely represented yet. Each "
        "frontier genre names its defining artists that the library lacks; "
        "feed one to a discovery run as a genre seed to explore it."
    ),
)
def genre_frontier(
    session: SessionDep,
    user: CurrentUserDep,
    owned_only: Annotated[
        bool,
        Query(
            description=(
                "Compute territory from playlists the account owns. Set false "
                "to also count followed playlists."
            )
        ),
    ] = True,
) -> FrontierResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.frontier,
        lambda: compute_frontier_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return FrontierResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/discovery/frontier"),
            "run": HalLink(href="/v1/discovery/run"),
        },
    )


@router.post(
    "/v1/discovery/run",
    summary="Run a discovery pass",
    description=(
        "Generates fresh candidates (similar-artist top tracks and seeded "
        "recommendations), resolves them to Spotify tracks, fetches their "
        "audio features, and finds preview audio. Restricted to one playlist "
        "when playlist_id is given. Tracks already in the library or "
        "previously rejected never enter the pool."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown playlist."}},
)
async def run_discovery_pass(
    body: DiscoveryRunBody,
    session: SessionDep,
    user: CurrentUserDep,
    runner: Annotated[DiscoveryRunner, Depends(get_discovery_runner)],
) -> DiscoveryRunResult:
    assert user.id is not None
    if body.playlist_id is not None:
        _require_playlist(session, user.id, body.playlist_id)
    if body.genre_seed is not None:
        if body.playlist_id is None:
            raise AppError(
                400,
                "Genre seed needs a playlist",
                detail="A genre-seeded pass targets one playlist — include playlist_id.",
                error_code="GENRE_SEED_REQUIRES_PLAYLIST",
            )
        genre = session.exec(
            select(Genre).where(func.lower(Genre.name) == body.genre_seed.casefold())
        ).first()
        if genre is None:
            raise AppError(
                404,
                "Genre not found",
                detail=f"No genre named {body.genre_seed!r} in the genre atlas.",
                error_code="GENRE_NOT_FOUND",
            )
    report = await runner(session, user, body.playlist_id, body.limit, body.genre_seed)
    return DiscoveryRunResult(
        playlists_processed=report.playlists_processed,
        generated_lastfm=report.generated_lastfm,
        generated_reccobeats=report.generated_reccobeats,
        generated_enao=report.generated_enao,
        excluded=report.excluded,
        resolved=report.resolved,
        unresolvable=report.unresolvable,
        features_fetched=report.features_fetched,
        previews_resolved=report.previews_resolved,
        lastfm_skipped=report.lastfm_skipped,
        errors=report.errors,
        links={
            "self": HalLink(href="/v1/discovery/run"),
            "playlists": HalLink(href="/v1/playlists"),
        },
    )
