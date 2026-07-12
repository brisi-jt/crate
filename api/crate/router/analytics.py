"""Analytics read endpoints and the recompute trigger.

Results come from the AnalyticsSnapshot cache: the first read after a sync or
enrichment pass computes and stores, later reads serve the stored payload.
All feature-derived numbers are library percentiles (0..1), not raw values.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from crate.deps import CurrentUserDep, SessionDep
from crate.errors import AppError, ProblemDetail
from crate.model.enums import SnapshotKind
from crate.model.orm import Playlist, User
from crate.services.analytics import engine
from crate.services.analytics.snapshots import get_or_compute

router = APIRouter(tags=["analytics"])

OwnedOnlyParam = Annotated[
    bool,
    Query(
        description=(
            "Limit analytics to playlists the account owns. Set false to also "
            "include followed playlists — a much larger set on most accounts."
        )
    ),
]


class HalLink(BaseModel):
    href: str


# ---------------------------------------------------------------- graph


class AcousticCentroid(BaseModel):
    """Playlist mean of three feature percentiles; the dashboard maps it to color."""

    acousticness: float = Field(ge=0, le=1)
    energy: float = Field(ge=0, le=1)
    valence: float = Field(ge=0, le=1)


class GraphNode(BaseModel):
    id: int = Field(description="Playlist id — matches /v1/playlists ids.")
    name: str
    track_count: int
    centroid: AcousticCentroid | None = Field(
        description="Null until the playlist has at least one enriched track."
    )


class GraphEdge(BaseModel):
    source: int = Field(description="Playlist id of one endpoint.")
    target: int = Field(description="Playlist id of the other endpoint.")
    shared: int = Field(description="Tracks the two playlists have in common.")
    subset: bool = Field(
        description="True when at least 90% of the smaller playlist lives inside the larger."
    )


class GraphCoverage(BaseModel):
    enriched_tracks: int
    total_tracks: int


class GraphResponse(BaseModel):
    """The playlist graph: one node per playlist, one edge per shared-track pair."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    coverage: GraphCoverage = Field(
        description="How much of the library has audio features — nodes without "
        "a centroid render as pending."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ---------------------------------------------------------- artist galaxy


class GalaxyTrackRef(BaseModel):
    id: int = Field(description="Track id — matches playlist track listings.")
    name: str


class GalaxySimilarArtist(BaseModel):
    name: str
    weight: float = Field(description="Listener-reported similarity strength, 0..1.")
    in_library: bool = Field(description="True when this artist also appears in the library.")


class GalaxyNode(BaseModel):
    id: str = Field(description="Stable artist key (lowercase name) — edge endpoints reference it.")
    name: str
    track_count: int = Field(description="Distinct library tracks crediting the artist.")
    playlist_count: int = Field(description="Playlists in scope holding the artist.")
    playlist_ids: list[int]
    centroid: AcousticCentroid | None = Field(
        description="Mean sound of the artist's enriched tracks; null until "
        "enrichment reaches them."
    )
    genres: list[str] = Field(description="Strongest genre tags for the artist, best first.")
    tracks: list[GalaxyTrackRef] = Field(
        description="The artist's library tracks, alphabetical, capped — "
        "track_count carries the full number."
    )
    similar: list[GalaxySimilarArtist] = Field(
        description="Artists listeners pair with this one, strongest first. "
        "Empty when no similarity data exists yet."
    )


class GalaxyEdge(BaseModel):
    source: str = Field(description="Artist key of one endpoint.")
    target: str = Field(description="Artist key of the other endpoint.")
    kind: str = Field(
        description="co_playlist — playlists hold both artists (weight = how "
        "many); similarity — listeners pair them (weight 0..1)."
    )
    weight: float


class GalaxyCoverage(BaseModel):
    """How much of the full artist set the capped payload shows."""

    artists_total: int
    artists_shown: int
    edges_total: int
    edges_shown: int


class ArtistGalaxyResponse(BaseModel):
    """The library's artists as a galaxy: nodes per artist, edges per relation."""

    nodes: list[GalaxyNode]
    edges: list[GalaxyEdge]
    coverage: GalaxyCoverage = Field(
        description="Large libraries are capped to the most connected artists "
        "— totals report what the cap dropped."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ------------------------------------------------------------- track map


class MapPointResource(BaseModel):
    track_id: int
    name: str
    artist: str
    x: float
    y: float
    cluster: int = Field(description="Density cluster label; -1 means no cluster (noise).")
    features: AcousticCentroid | None = Field(
        default=None,
        description="The track's three color-feature percentiles; null until "
        "enrichment reaches it. Drives the node's exact acoustic color.",
    )
    playlist_ids: list[int] = Field(
        default_factory=list,
        description="Playlists in scope that hold this track — the membership join, server-side.",
    )


class SplitClusterShare(BaseModel):
    cluster: int
    share: float = Field(description="Share of the playlist's clustered tracks in this cluster.")


class SplitSuggestionResource(BaseModel):
    playlist_id: int
    name: str
    clusters: list[SplitClusterShare]


class MergeSuggestionResource(BaseModel):
    cluster: int
    playlist_ids: list[int]
    playlist_names: list[str]


class TrackMapResponse(BaseModel):
    """All enriched tracks projected to 2D, with density clusters compared
    against the playlists that hold them."""

    points: list[MapPointResource]
    cluster_count: int
    noise_count: int
    ari: float | None = Field(
        description="Agreement between clusters and playlists (adjusted Rand "
        "index, 1 = identical grouping). Null until computable."
    )
    split_suggestions: list[SplitSuggestionResource] = Field(
        description="Playlists straddling two or more sound clusters."
    )
    merge_suggestions: list[MergeSuggestionResource] = Field(
        description="Playlists whose tracks share one sound cluster."
    )
    layout_hash: str | None = Field(
        description="Fingerprint of the projected layout; identical library "
        "state reproduces it exactly."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# -------------------------------------------------------------- temporal


class DriftPointResource(BaseModel):
    quarter: str = Field(description="Calendar quarter, e.g. 2026Q1.")
    energy: float
    valence: float
    acousticness: float


class GrowthPointResource(BaseModel):
    quarter: str
    track_count: int


class GrowthCurveResource(BaseModel):
    playlist_id: int
    name: str
    points: list[GrowthPointResource]


class TemporalResponse(BaseModel):
    """How the library moved over time, from track add timestamps."""

    drift: list[DriftPointResource] = Field(
        description="Mean sound of the tracks added each quarter, as library "
        "percentiles. Quarters without enriched adds are omitted."
    )
    growth: list[GrowthCurveResource] = Field(
        description="Cumulative playlist sizes per quarter, sharing one "
        "quarter axis across playlists."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# --------------------------------------------------------- library stats


class DuplicateResource(BaseModel):
    isrc: str | None
    name: str
    artist: str
    playlists: list[str] = Field(description="Playlist names holding a copy.")


class ClusterSummary(BaseModel):
    ari: float | None
    cluster_count: int
    split_suggestions: int
    merge_suggestions: int


class LibraryStatsResponse(BaseModel):
    """The library stats screen in one call: drift, duplicates, cluster summary."""

    drift: list[DriftPointResource]
    duplicates: list[DuplicateResource] = Field(
        description="Same recording under different Spotify ids across the "
        "library, plus tracks repeated inside one playlist."
    )
    clusters: ClusterSummary | None = Field(
        description="Summary of the track map; null until enough enriched tracks exist."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ---------------------------------------------------- playlist analytics


class OutlierResource(BaseModel):
    track_id: int
    name: str
    artist: str
    distance: float = Field(
        description="Distance from the playlist's sound centroid — bigger is stranger."
    )


class OverlapResource(BaseModel):
    playlist_id: int
    name: str
    shared: int
    containment: float | None = Field(
        description="Shared share of the smaller playlist; 1.0 means full containment."
    )


class FingerprintEntry(BaseModel):
    feature: str
    percentile: float = Field(description="Playlist mean library-percentile for the feature, 0..1.")


class FlowSummary(BaseModel):
    score: float = Field(description="Mean transition quality of the current order, 0-100.")


class PlaylistAnalyticsResponse(BaseModel):
    """One playlist's structure numbers for the detail panel."""

    cohesion: float | None = Field(
        description="Mean pairwise distance between the playlist's tracks in "
        "percentile space, 0 (uniform) to 1 (scattered). Null until two "
        "tracks are enriched."
    )
    outliers: list[OutlierResource] = Field(description="Most distant tracks, strangest first.")
    overlaps: list[OverlapResource] = Field(
        description="Playlists sharing tracks, most shared first."
    )
    fingerprint: list[FingerprintEntry] | None = Field(
        description="Per-feature sound profile; null until enrichment reaches the playlist."
    )
    flow: FlowSummary | None
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# -------------------------------------------------------------------- flow


class TransitionResource(BaseModel):
    from_track_id: int
    to_track_id: int
    score: float = Field(description="Key + tempo compatibility of this transition, 0-100.")


class FlowResponse(BaseModel):
    """Harmonic/tempo flow of a playlist's current order, plus a reorder suggestion."""

    score: float | None = Field(
        description="Mean transition score of the current order, 0-100. Null "
        "for playlists under two tracks."
    )
    transitions: list[TransitionResource] = Field(
        description="Each consecutive pair in the current order."
    )
    suggested_order: list[int] | None = Field(
        description="Track ids in the suggested play order. Null when the "
        "playlist is too small (under 3 tracks) or too large to reorder."
    )
    suggested_score: float | None = Field(
        description="Flow score the suggested order would achieve."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# --------------------------------------------------------------- recompute


class RecomputeResponse(BaseModel):
    """Counts from a full analytics rebuild."""

    invalidated: int = Field(description="Cached payloads dropped.")
    computed: int = Field(description="Payloads now cached after the rebuild.")
    links: dict[str, HalLink] = Field(serialization_alias="_links")


# ------------------------------------------------------------------ routes


def _require_playlist(session: SessionDep, user: User, playlist_id: int) -> Playlist:
    playlist = session.exec(
        select(Playlist)
        .where(Playlist.id == playlist_id)
        .where(Playlist.user_id == user.id)
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


@router.get(
    "/v1/graph/playlists",
    summary="Playlist graph",
    description=(
        "The library as a graph: playlists as nodes sized by track count and "
        "colored from their acoustic centroid, edges weighted by shared "
        "tracks. Subset edges mark playlists that live almost entirely "
        "inside another."
    ),
)
def playlist_graph(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> GraphResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.graph,
        lambda: engine.compute_graph_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return GraphResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/graph/playlists"),
            "map": HalLink(href="/v1/map/tracks"),
            "recompute": HalLink(href="/v1/analytics/recompute"),
        },
    )


@router.get(
    "/v1/graph/artists",
    summary="Artist galaxy",
    description=(
        "Every credited artist across the playlists in scope, as a galaxy: "
        "nodes sized by how many library tracks the artist appears on and "
        "colored from the mean sound of those tracks, with two kinds of "
        "edges — artists sharing playlists, and artists listeners report as "
        "similar. Each node carries what the artist card shows: library "
        "tracks, owning playlists, genre tags, and similar artists. Very "
        "large libraries are capped to the most connected artists."
    ),
)
def artist_galaxy(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> ArtistGalaxyResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.artist_galaxy,
        lambda: engine.compute_artist_galaxy_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return ArtistGalaxyResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/graph/artists"),
            "graph": HalLink(href="/v1/graph/playlists"),
            "map": HalLink(href="/v1/map/tracks"),
        },
    )


@router.get(
    "/v1/map/tracks",
    summary="Track map",
    description=(
        "Every enriched track projected onto a 2D sound map, grouped into "
        "density clusters and compared against the playlists: playlists "
        "spanning several clusters are split candidates, playlists sharing "
        "one cluster are merge candidates."
    ),
)
def track_map(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> TrackMapResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.track_map,
        lambda: engine.compute_track_map_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return TrackMapResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/map/tracks"),
            "graph": HalLink(href="/v1/graph/playlists"),
        },
    )


@router.get(
    "/v1/analytics/temporal",
    summary="Temporal analytics",
    description=(
        "Quarterly view of the library: how the sound of newly added tracks "
        "drifted, and how each playlist grew."
    ),
)
def temporal_analytics(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> TemporalResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.temporal,
        lambda: engine.compute_temporal_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return TemporalResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/analytics/temporal"),
            "library": HalLink(href="/v1/analytics/library"),
        },
    )


@router.get(
    "/v1/analytics/library",
    summary="Library stats",
    description=(
        "Library-wide health in one payload: quarterly sound drift, duplicate "
        "recordings, and how well the playlists match the library's natural "
        "sound clusters."
    ),
)
def library_stats(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> LibraryStatsResponse:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.library_stats,
        lambda: engine.compute_library_stats_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
    return LibraryStatsResponse(
        **payload,
        links={
            "self": HalLink(href="/v1/analytics/library"),
            "temporal": HalLink(href="/v1/analytics/temporal"),
            "map": HalLink(href="/v1/map/tracks"),
        },
    )


@router.get(
    "/v1/playlists/{playlist_id}/analytics",
    summary="Playlist analytics",
    description=(
        "The numbers behind one playlist: how uniform it sounds (cohesion), "
        "which tracks sit farthest from its center (outliers), which "
        "playlists it shares tracks with, its per-feature sound fingerprint, "
        "and the flow score of its current order."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown playlist."}},
)
def playlist_analytics(
    playlist_id: int, session: SessionDep, user: CurrentUserDep
) -> PlaylistAnalyticsResponse:
    playlist = _require_playlist(session, user, playlist_id)
    # Owned playlists are analyzed against the owned library (overlaps stay
    # inside the curated set); a followed playlist only exists in the full
    # library, so it is analyzed against that.
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.playlist_analytics,
        lambda: engine.compute_playlist_analytics_payload(
            session, user, playlist_id, owned_only=playlist.is_owned
        ),
        playlist_id=playlist_id,
        owned_only=playlist.is_owned,
    )
    return PlaylistAnalyticsResponse(
        **payload,
        links={
            "self": HalLink(href=f"/v1/playlists/{playlist_id}/analytics"),
            "playlist": HalLink(href=f"/v1/playlists/{playlist_id}"),
            "flow": HalLink(href=f"/v1/playlists/{playlist_id}/flow"),
        },
    )


@router.get(
    "/v1/playlists/{playlist_id}/flow",
    summary="Playlist flow",
    description=(
        "How well the playlist's current order flows track to track, scored "
        "on key compatibility (Camelot wheel) and tempo. Includes a suggested "
        "reorder that improves the flow, ready to apply as a new track order."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown playlist."}},
)
def playlist_flow(playlist_id: int, session: SessionDep, user: CurrentUserDep) -> FlowResponse:
    playlist = _require_playlist(session, user, playlist_id)
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.flow,
        lambda: engine.compute_flow_payload(
            session, user, playlist_id, owned_only=playlist.is_owned
        ),
        playlist_id=playlist_id,
        owned_only=playlist.is_owned,
    )
    return FlowResponse(
        **payload,
        links={
            "self": HalLink(href=f"/v1/playlists/{playlist_id}/flow"),
            "playlist": HalLink(href=f"/v1/playlists/{playlist_id}"),
            "analytics": HalLink(href=f"/v1/playlists/{playlist_id}/analytics"),
        },
    )


@router.post(
    "/v1/analytics/recompute",
    summary="Recompute all analytics",
    description=(
        "Drops every cached analytics payload and rebuilds the set for the "
        "requested scope — graph, track map, temporal, library stats, and "
        "per-playlist analytics. Runs synchronously; cached reads stay fast "
        "afterwards. Normally unnecessary: sync and enrichment already "
        "refresh the cache."
    ),
)
def recompute_analytics(
    session: SessionDep, user: CurrentUserDep, owned_only: OwnedOnlyParam = True
) -> RecomputeResponse:
    counts: dict[str, Any] = engine.recompute_all(session, user, owned_only=owned_only)
    return RecomputeResponse(
        **counts,
        links={
            "self": HalLink(href="/v1/analytics/recompute"),
            "graph": HalLink(href="/v1/graph/playlists"),
            "library": HalLink(href="/v1/analytics/library"),
        },
    )
