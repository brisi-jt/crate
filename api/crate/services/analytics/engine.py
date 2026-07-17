"""Payload builders and the AnalyticsSnapshot cache.

Each compute_* function produces the JSON body its endpoint serves. Reads go
through get_or_compute, so results persist until a sync or enrichment pass
invalidates them and the next read recomputes.

Builders accept an optional AnalyticsContext so a full recompute loads the
library once instead of once per payload — the difference between seconds
and minutes at 60 playlists.
"""

from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise
from typing import Any

import numpy as np
from sqlmodel import Session, col, func, select

from crate.model.enums import SnapshotKind
from crate.model.orm import (
    AnalyticsSnapshot,
    Artist,
    ArtistGenre,
    ArtistSimilarity,
    Genre,
    User,
)
from crate.services.analytics.clustering import clustering_features, compute_track_map
from crate.services.analytics.flow import TrackAudio, flow_score, suggest_order, transition_score
from crate.services.analytics.galaxy import (
    MAX_GALAXY_EDGES,
    MAX_GALAXY_NODES,
    cap_edges,
    co_playlist_weights,
    order_by_degree,
)
from crate.services.analytics.loaders import (
    GENRE_CLUSTER_WEIGHT,
    LibrarySnapshot,
    load_genre_vectors,
    load_library,
    load_percentile_space,
    load_track_credits,
)
from crate.services.analytics.percentiles import PercentileSpace
from crate.services.analytics.snapshots import get_or_compute, invalidate_snapshots
from crate.services.analytics.structure import (
    DEFAULT_OUTLIER_COUNT,
    OverlapEdge,
    cohesion,
    find_duplicate_groups,
    outliers,
    overlap_edges,
)
from crate.services.analytics.temporal import AddRecord, drift_by_quarter, growth_curves

# The three features whose playlist centroid drives node color on the map.
CENTROID_FEATURES = ("acousticness", "energy", "valence")

# Per-node payload budgets for the artist galaxy: enough for the docked
# artist card without shipping whole rosters for every node.
GALAXY_GENRES_PER_ARTIST = 3
GALAXY_TRACKS_PER_ARTIST = 12
GALAXY_SIMILAR_PER_ARTIST = 8

# Chunk size for IN(...) queries over track ids / artist names.
_IN_CHUNK = 400

# Greedy reorder is O(n^2) transitions; beyond this the suggestion is skipped
# rather than stalling the request.
MAX_REORDER_TRACKS = 300


@dataclass
class AnalyticsContext:
    """One load of everything the payload builders share.

    Endpoint reads build one per request; recompute_all builds one for the
    whole pass. The derived properties are computed lazily and cached.
    """

    library: LibrarySnapshot
    space: PercentileSpace

    @classmethod
    def load(cls, session: Session, user_id: int, owned_only: bool = True) -> "AnalyticsContext":
        """Load the user's library at the requested playlist scope.

        The percentile space stays catalog-wide either way — a track's rank is
        relative to everything enriched, not to the playlists in view.
        """
        return cls(
            library=load_library(session, user_id, owned_only=owned_only),
            space=load_percentile_space(session),
        )

    @cached_property
    def vectors(self) -> dict[int, dict[str, float]]:
        """track id -> percentile vector, for tracks with present features."""
        return {
            track_id: self.space.transform(values)
            for track_id, values in sorted(self.library.features.items())
        }

    @cached_property
    def edges(self) -> list[OverlapEdge]:
        return overlap_edges(self.library.memberships)


def _context(
    session: Session, user: User, ctx: AnalyticsContext | None, owned_only: bool
) -> AnalyticsContext:
    assert user.id is not None
    return ctx if ctx is not None else AnalyticsContext.load(session, user.id, owned_only)


# ------------------------------------------------------------ shared helpers


def _playlist_matrix(
    track_ids: set[int],
    vectors: dict[int, dict[str, float]],
    features: tuple[str, ...],
) -> tuple[np.ndarray, list[int]]:
    """(matrix, aligned track ids) for a playlist's enriched tracks."""
    enriched = sorted(tid for tid in track_ids if tid in vectors)
    matrix = np.array(
        [[vectors[tid][feature] for feature in features] for tid in enriched], dtype=float
    ).reshape(len(enriched), len(features))
    return matrix, enriched


def _centroid(track_ids: set[int], vectors: dict[int, dict[str, float]]) -> dict[str, float] | None:
    enriched = [vectors[tid] for tid in sorted(track_ids) if tid in vectors]
    if not enriched:
        return None
    return {
        feature: round(sum(vector[feature] for vector in enriched) / len(enriched), 4)
        for feature in CENTROID_FEATURES
    }


def _track_audio(library: LibrarySnapshot, track_id: int) -> TrackAudio:
    tempo, key, mode = library.audio.get(track_id, (None, None, None))
    return TrackAudio(track_id=track_id, tempo=tempo, key=key, mode=mode)


# ------------------------------------------------------------------ payloads


def compute_graph_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    ctx = _context(session, user, ctx, owned_only)
    library, vectors = ctx.library, ctx.vectors

    nodes = [
        {
            "id": playlist_id,
            "name": library.playlist_names[playlist_id],
            "image_url": library.playlist_images.get(playlist_id),
            "track_count": len(library.occurrences[playlist_id]),
            "centroid": _centroid(library.memberships[playlist_id], vectors),
        }
        for playlist_id in sorted(library.playlist_names)
    ]
    edges = [
        {
            "source": edge.source,
            "target": edge.target,
            "shared": edge.shared,
            "subset": edge.subset,
        }
        for edge in ctx.edges
    ]
    total_tracks = len(library.track_meta)
    enriched_tracks = sum(1 for tid in library.track_meta if tid in vectors)
    return {
        "nodes": nodes,
        "edges": edges,
        "coverage": {"enriched_tracks": enriched_tracks, "total_tracks": total_tracks},
    }


def compute_playlist_analytics_payload(
    session: Session,
    user: User,
    playlist_id: int,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    ctx = _context(session, user, ctx, owned_only)
    library, vectors = ctx.library, ctx.vectors
    members = library.memberships.get(playlist_id, set())

    matrix, enriched_ids = _playlist_matrix(members, vectors, ctx.space.features)

    outlier_entries: list[dict[str, Any]] = []
    if enriched_ids:
        result = outliers(matrix, enriched_ids, top_n=DEFAULT_OUTLIER_COUNT)
        for entry in result.entries:
            meta = library.track_meta.get(entry.track_id, {})
            outlier_entries.append(
                {
                    "track_id": entry.track_id,
                    "name": meta.get("name", ""),
                    "artist": meta.get("artist", ""),
                    "distance": round(entry.distance, 4),
                }
            )

    overlap_entries = [
        {
            "playlist_id": edge.target if edge.source == playlist_id else edge.source,
            "name": library.playlist_names.get(
                edge.target if edge.source == playlist_id else edge.source, ""
            ),
            "shared": edge.shared,
            "containment": round(edge.containment, 4),
        }
        for edge in ctx.edges
        if playlist_id in (edge.source, edge.target)
    ]
    overlap_entries.sort(key=lambda entry: (-entry["shared"], entry["playlist_id"]))

    fingerprint = None
    if enriched_ids:
        means = matrix.mean(axis=0)
        fingerprint = [
            {"feature": feature, "percentile": round(float(means[i]), 4)}
            for i, feature in enumerate(ctx.space.features)
        ]

    ordered = [_track_audio(library, tid) for tid in library.occurrences.get(playlist_id, [])]
    current_flow = flow_score(ordered)

    playlist_cohesion = cohesion(matrix)
    return {
        "cohesion": round(playlist_cohesion, 4) if playlist_cohesion is not None else None,
        "outliers": outlier_entries,
        "overlaps": overlap_entries,
        "fingerprint": fingerprint,
        "flow": {"score": round(current_flow, 2)} if current_flow is not None else None,
    }


def compute_flow_payload(
    session: Session,
    user: User,
    playlist_id: int,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    ctx = _context(session, user, ctx, owned_only)
    library = ctx.library
    ordered = [_track_audio(library, tid) for tid in library.occurrences.get(playlist_id, [])]

    transitions = [
        {
            "from_track_id": a.track_id,
            "to_track_id": b.track_id,
            "score": round(transition_score(a, b), 2),
        }
        for a, b in pairwise(ordered)
    ]
    current = flow_score(ordered)

    suggestion = None
    if len(ordered) <= MAX_REORDER_TRACKS:
        suggestion = suggest_order(ordered)

    return {
        "score": round(current, 2) if current is not None else None,
        "transitions": transitions,
        "suggested_order": suggestion.order if suggestion else None,
        "suggested_score": round(suggestion.score, 2) if suggestion else None,
    }


def _add_records(library: LibrarySnapshot, vectors: dict[int, dict[str, float]]) -> list[AddRecord]:
    return [
        AddRecord(
            playlist_id=playlist_id,
            track_id=track_id,
            added_at=added_at,
            centroid=(
                {feature: vectors[track_id][feature] for feature in CENTROID_FEATURES}
                if track_id in vectors
                else None
            ),
        )
        for playlist_id, track_id, added_at in library.adds
    ]


def compute_temporal_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    ctx = _context(session, user, ctx, owned_only)
    library = ctx.library
    records = _add_records(library, ctx.vectors)

    drift = [
        {
            "quarter": point.quarter,
            "energy": round(point.energy, 4),
            "valence": round(point.valence, 4),
            "acousticness": round(point.acousticness, 4),
        }
        for point in drift_by_quarter(records)
    ]
    growth = [
        {
            "playlist_id": curve.playlist_id,
            "name": library.playlist_names.get(curve.playlist_id, ""),
            "points": [
                {"quarter": point.quarter, "track_count": point.track_count}
                for point in curve.points
            ],
        }
        for curve in growth_curves(records)
    ]
    return {"drift": drift, "growth": growth}


def compute_track_map_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    ctx = _context(session, user, ctx, owned_only)
    library, vectors = ctx.library, ctx.vectors

    track_ids = sorted(vectors)
    # Cluster on the decorrelated feature set (loudness dropped, M3); the color
    # features below still use the full percentile vector.
    cluster_features = clustering_features(ctx.space.features)
    matrix = np.array(
        [[vectors[tid][feature] for feature in cluster_features] for tid in track_ids],
        dtype=float,
    ).reshape(len(track_ids), len(cluster_features))

    # G3: per-track genre block, blended into the clustering distance. Weighted
    # so genre pulls against the acoustic axes without swamping them.
    genre_vectors, _genre_names = load_genre_vectors(session, track_ids)
    genre_matrix = None
    genre_dims = len(_genre_names)
    if genre_dims:
        genre_matrix = (
            np.array(
                [genre_vectors[tid] for tid in track_ids],
                dtype=float,
            ).reshape(len(track_ids), genre_dims)
            * GENRE_CLUSTER_WEIGHT
        )

    result = compute_track_map(matrix, track_ids, library.memberships, genre_matrix=genre_matrix)
    if result is None:
        return {
            "points": [],
            "cluster_count": 0,
            "noise_count": 0,
            "ari": None,
            "split_suggestions": [],
            "merge_suggestions": [],
            "layout_hash": None,
        }

    # track id -> the playlists (in scope) that hold it, for per-point membership.
    track_playlists: dict[int, list[int]] = {}
    for playlist_id in sorted(library.memberships):
        for track_id in library.memberships[playlist_id]:
            track_playlists.setdefault(track_id, []).append(playlist_id)

    return {
        "points": [
            {
                "track_id": point.track_id,
                "name": library.track_meta.get(point.track_id, {}).get("name", ""),
                "artist": library.track_meta.get(point.track_id, {}).get("artist", ""),
                "album_image_url": library.track_meta.get(point.track_id, {}).get(
                    "album_image_url"
                ),
                "x": round(point.x, 4),
                "y": round(point.y, 4),
                "cluster": point.cluster,
                # The three color features per track (matches the web zod
                # `features` optional shape), so the field colors each node from
                # its own sound rather than deriving it client-side.
                "features": _centroid({point.track_id}, vectors),
                "playlist_ids": track_playlists.get(point.track_id, []),
            }
            for point in result.points
        ],
        "cluster_count": result.cluster_count,
        "noise_count": result.noise_count,
        "ari": round(result.ari, 4) if result.ari is not None else None,
        "split_suggestions": [
            {
                "playlist_id": suggestion.playlist_id,
                "name": library.playlist_names.get(suggestion.playlist_id, ""),
                "clusters": [
                    {"cluster": label, "share": round(share, 4)}
                    for label, share in suggestion.clusters
                ],
            }
            for suggestion in result.split_suggestions
        ],
        "merge_suggestions": [
            {
                "cluster": suggestion.cluster,
                "playlist_ids": suggestion.playlist_ids,
                "playlist_names": [
                    library.playlist_names.get(pid, "") for pid in suggestion.playlist_ids
                ],
            }
            for suggestion in result.merge_suggestions
        ],
        "layout_hash": result.layout_hash,
    }


def _artist_genre_tags(session: Session, keys: list[str]) -> dict[str, list[str]]:
    """artist key -> ENAO genre names by descending membership weight."""
    weighted: dict[str, list[tuple[float, int, str]]] = {}
    ordered = sorted(keys)
    for start in range(0, len(ordered), _IN_CHUNK):
        chunk = ordered[start : start + _IN_CHUNK]
        rows = session.exec(
            select(ArtistGenre, Genre)
            .where(ArtistGenre.genre_id == Genre.id)  # type: ignore[arg-type]
            .where(func.lower(ArtistGenre.artist_name).in_(chunk))
        ).all()
        for membership, genre in rows:
            key = membership.artist_name.casefold()
            weighted.setdefault(key, []).append(
                (-membership.weight, genre.enao_rank or 0, genre.name)
            )
    return {
        key: [name for _, _, name in sorted(entries)[:GALAXY_GENRES_PER_ARTIST]]
        for key, entries in weighted.items()
    }


def compute_artist_galaxy_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    """Artists across the in-scope playlists as a galaxy.

    Nodes are keyed by lowercase artist name (the credit is the identity —
    a catalog Artist row is optional and only adds similarity data). Edges
    come in two kinds: co_playlist (playlists holding both artists) and
    similarity (listener-reported, weight 0..1). Node and edge counts are
    capped for canvas rendering; coverage reports what the cap dropped.
    """
    ctx = _context(session, user, ctx, owned_only)
    library, vectors = ctx.library, ctx.vectors
    credits = load_track_credits(session, list(library.track_meta))

    display: dict[str, str] = {}
    artist_tracks: dict[str, set[int]] = {}
    for track_id, names in credits.items():
        for name in names:
            key = name.casefold()
            display.setdefault(key, name)
            artist_tracks.setdefault(key, set()).add(track_id)

    playlist_artists: dict[int, set[str]] = {}
    artist_playlists: dict[str, set[int]] = {}
    for playlist_id, members in library.memberships.items():
        keys = {name.casefold() for track_id in members for name in credits.get(track_id, [])}
        playlist_artists[playlist_id] = keys
        for key in keys:
            artist_playlists.setdefault(key, set()).add(playlist_id)

    weights = co_playlist_weights(playlist_artists)
    track_counts = {key: len(tracks) for key, tracks in artist_tracks.items()}
    ordered = order_by_degree(sorted(artist_tracks), weights, track_counts)
    kept = ordered[:MAX_GALAXY_NODES]
    kept_set = set(kept)

    # Catalog rows (where they exist) unlock the similarity layer and the
    # artist photo (keyed by casefolded name — the node identity).
    catalog_ids: dict[int, str] = {}
    artist_images: dict[str, str | None] = {}
    for artist in session.exec(select(Artist)).all():
        key = artist.name.casefold()
        if key in kept_set:
            if artist.id is not None:
                catalog_ids.setdefault(artist.id, key)
            if artist.image_url_sm and key not in artist_images:
                artist_images[key] = artist.image_url_sm

    similar_weights: dict[str, dict[str, float]] = {}
    pair_weights: dict[tuple[str, str], float] = {}
    if catalog_ids:
        edges = session.exec(
            select(ArtistSimilarity).where(col(ArtistSimilarity.artist_id).in_(list(catalog_ids)))
        ).all()
        for edge in edges:
            source_key = catalog_ids[edge.artist_id]
            target_key = edge.similar_artist_name.casefold()
            if target_key == source_key:
                continue
            per_source = similar_weights.setdefault(source_key, {})
            per_source[edge.similar_artist_name] = max(
                per_source.get(edge.similar_artist_name, 0.0), edge.weight
            )
            if target_key in kept_set:
                pair = (min(source_key, target_key), max(source_key, target_key))
                pair_weights[pair] = max(pair_weights.get(pair, 0.0), edge.weight)

    similarity_edges = [
        {"source": a, "target": b, "kind": "similarity", "weight": round(weight, 4)}
        for (a, b), weight in sorted(pair_weights.items())
    ]
    co_edges = [
        {"source": a, "target": b, "kind": "co_playlist", "weight": float(weight)}
        for (a, b), weight in sorted(weights.items())
        if a in kept_set and b in kept_set
    ]
    edges_total = len(co_edges) + len(similarity_edges)
    edges = cap_edges(co_edges, similarity_edges, MAX_GALAXY_EDGES)

    genre_tags = _artist_genre_tags(session, kept)

    nodes: list[dict[str, Any]] = []
    for key in sorted(kept, key=lambda k: (-track_counts[k], k)):
        member_tracks = sorted(
            artist_tracks[key],
            key=lambda tid: (library.track_meta[tid]["name"], tid),
        )
        similar = [
            {
                "name": name,
                "weight": round(weight, 4),
                "in_library": name.casefold() in artist_tracks,
            }
            for name, weight in sorted(
                similar_weights.get(key, {}).items(), key=lambda item: (-item[1], item[0])
            )[:GALAXY_SIMILAR_PER_ARTIST]
        ]
        nodes.append(
            {
                "id": key,
                "name": display[key],
                "image_url": artist_images.get(key),
                "track_count": track_counts[key],
                "playlist_count": len(artist_playlists.get(key, ())),
                "playlist_ids": sorted(artist_playlists.get(key, ())),
                "centroid": _centroid(artist_tracks[key], vectors),
                "genres": genre_tags.get(key, []),
                "tracks": [
                    {"id": tid, "name": library.track_meta[tid]["name"]}
                    for tid in member_tracks[:GALAXY_TRACKS_PER_ARTIST]
                ],
                "similar": similar,
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "coverage": {
            "artists_total": len(artist_tracks),
            "artists_shown": len(kept),
            "edges_total": edges_total,
            "edges_shown": len(edges),
        },
    }


def compute_library_stats_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    """Drift + duplicates + a cluster summary — the library stats screen's body.

    The drift and cluster inputs come through the snapshot cache (computing on
    a miss), so the UMAP projection never runs twice for one library state.
    """
    ctx = _context(session, user, ctx, owned_only)
    library = ctx.library

    temporal = get_or_compute(
        session,
        user,
        SnapshotKind.temporal,
        lambda: compute_temporal_payload(session, user, ctx),
        owned_only=owned_only,
    )
    track_map = get_or_compute(
        session,
        user,
        SnapshotKind.track_map,
        lambda: compute_track_map_payload(session, user, ctx),
        owned_only=owned_only,
    )

    duplicates = [
        {
            "isrc": group.isrc,
            "name": group.name,
            "artist": group.artist,
            "playlists": group.playlists,
        }
        for group in find_duplicate_groups(
            [{"track_id": tid, **meta} for tid, meta in sorted(library.track_meta.items())],
            library.memberships,
            library.playlist_names,
            occurrences=library.occurrences,
        )
    ]

    clusters = None
    if track_map["layout_hash"] is not None:
        clusters = {
            "ari": track_map["ari"],
            "cluster_count": track_map["cluster_count"],
            "split_suggestions": len(track_map["split_suggestions"]),
            "merge_suggestions": len(track_map["merge_suggestions"]),
        }

    return {"drift": temporal["drift"], "duplicates": duplicates, "clusters": clusters}


# ----------------------------------------------------------------- recompute


def recompute_all(session: Session, user: User, owned_only: bool = True) -> dict[str, int]:
    """Drop every cached payload for the user and rebuild the requested scope.

    Both scopes' caches are dropped (the underlying data changed for both);
    library-level payloads are rebuilt for the requested scope, and the other
    scope refills lazily on its next read. Per-playlist payloads are keyed to
    the scope their reads use — owned playlists to the owned library, followed
    playlists (in scope only when owned_only is false) to the full library.
    """
    assert user.id is not None
    invalidated = invalidate_snapshots(session, user.id)
    session.commit()

    owned_ctx = AnalyticsContext.load(session, user.id, owned_only=True)
    library_ctx = (
        owned_ctx if owned_only else AnalyticsContext.load(session, user.id, owned_only=False)
    )

    get_or_compute(
        session,
        user,
        SnapshotKind.graph,
        lambda: compute_graph_payload(session, user, library_ctx),
        owned_only=owned_only,
    )
    get_or_compute(
        session,
        user,
        SnapshotKind.track_map,
        lambda: compute_track_map_payload(session, user, library_ctx),
        owned_only=owned_only,
    )
    get_or_compute(
        session,
        user,
        SnapshotKind.temporal,
        lambda: compute_temporal_payload(session, user, library_ctx),
        owned_only=owned_only,
    )
    get_or_compute(
        session,
        user,
        SnapshotKind.library_stats,
        lambda: compute_library_stats_payload(session, user, library_ctx, owned_only=owned_only),
        owned_only=owned_only,
    )

    owned_ids = set(owned_ctx.library.playlist_names)
    for playlist_id in sorted(library_ctx.library.playlist_names):
        is_owned = playlist_id in owned_ids
        ctx = owned_ctx if is_owned else library_ctx
        get_or_compute(
            session,
            user,
            SnapshotKind.playlist_analytics,
            lambda pid=playlist_id, c=ctx: compute_playlist_analytics_payload(
                session, user, pid, c
            ),
            playlist_id=playlist_id,
            owned_only=is_owned,
        )
        get_or_compute(
            session,
            user,
            SnapshotKind.flow,
            lambda pid=playlist_id, c=ctx: compute_flow_payload(session, user, pid, c),
            playlist_id=playlist_id,
            owned_only=is_owned,
        )

    computed = len(
        session.exec(select(AnalyticsSnapshot.id).where(AnalyticsSnapshot.user_id == user.id)).all()
    )
    return {"invalidated": invalidated, "computed": computed}


def precompute_track_map(session: Session, user: User, owned_only: bool = True) -> None:
    """Fill the track_map snapshot for one scope if it is missing.

    The heavy UMAP+HDBSCAN never runs in the request path (it once crashed the
    server): the map endpoint returns 202 on a cache miss and schedules this,
    and the post-sync hook calls it warm. get_or_compute is a no-op when the
    snapshot already exists, so a burst of cold-cache requests coalesces onto
    one compute rather than storming many.
    """
    get_or_compute(
        session,
        user,
        SnapshotKind.track_map,
        lambda: compute_track_map_payload(session, user, owned_only=owned_only),
        owned_only=owned_only,
    )
