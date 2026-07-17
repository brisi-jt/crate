"""Database -> plain-structure loaders for the analytics engine.

The metric modules are pure functions over sets, dicts, and numpy arrays;
everything ORM-shaped stays in here.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlmodel import Session, col, func, select

from crate.model.enums import FeatureStatus
from crate.model.orm import ArtistGenre, Genre, Playlist, PlaylistTrack, Track, TrackFeatures
from crate.services.analytics.percentiles import PercentileSpace
from crate.services.enrichment.calibration import CALIBRATED_FEATURES


@dataclass
class LibrarySnapshot:
    """Everything analytics needs about one user's library, loaded once."""

    # playlist id -> distinct track ids
    memberships: dict[int, set[int]] = field(default_factory=dict)
    # playlist id -> track ids in position order (repeats preserved)
    occurrences: dict[int, list[int]] = field(default_factory=dict)
    playlist_names: dict[int, str] = field(default_factory=dict)
    # playlist id -> Spotify cover url, when it has one
    playlist_images: dict[int, str | None] = field(default_factory=dict)
    # track id -> {"spotify_id", "isrc", "name", "artist", "album_image_url"}
    track_meta: dict[int, dict[str, Any]] = field(default_factory=dict)
    # track id -> raw feature values (present rows only)
    features: dict[int, dict[str, float | None]] = field(default_factory=dict)
    # track id -> (tempo, key, mode) for flow scoring
    audio: dict[int, tuple[float | None, int | None, int | None]] = field(default_factory=dict)
    # playlist track rows as (playlist_id, track_id, added_at)
    adds: list[tuple[int, int, Any]] = field(default_factory=list)


def primary_artist(track: Track) -> str:
    names = [str(entry["name"]) for entry in track.artists if entry.get("name")]
    return names[0] if names else ""


def load_library(session: Session, user_id: int, owned_only: bool = False) -> LibrarySnapshot:
    """One user's playlists with memberships, metadata, and features.

    owned_only drops followed playlists — and with them every track reachable
    only by following. Spotify accounts follow far more than they curate, so
    analytics default to the owned scope at their own entry points.
    """
    snapshot = LibrarySnapshot()

    statement = (
        select(Playlist).where(Playlist.user_id == user_id).where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    )
    if owned_only:
        statement = statement.where(Playlist.is_owned == True)  # noqa: E712 — SQL expression
    playlists = session.exec(statement).all()
    for playlist in playlists:
        assert playlist.id is not None
        snapshot.playlist_names[playlist.id] = playlist.name
        snapshot.playlist_images[playlist.id] = playlist.image_url
        snapshot.memberships[playlist.id] = set()
        snapshot.occurrences[playlist.id] = []

    if not playlists:
        return snapshot

    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.user_id == user_id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(PlaylistTrack.playlist_id, PlaylistTrack.position)
    ).all()
    for membership, track in rows:
        if membership.playlist_id not in snapshot.memberships:
            continue  # out-of-scope playlist: deleted, or followed under owned_only
        assert track.id is not None
        snapshot.memberships[membership.playlist_id].add(track.id)
        snapshot.occurrences[membership.playlist_id].append(track.id)
        snapshot.adds.append((membership.playlist_id, track.id, membership.added_at))
        if track.id not in snapshot.track_meta:
            snapshot.track_meta[track.id] = {
                "spotify_id": track.spotify_id,
                "isrc": track.isrc,
                "name": track.name,
                "artist": primary_artist(track),
                # Small album-art thumb for the map/field hover card; null until
                # a sync or backfill has imaged the track's album.
                "album_image_url": track.image_url_sm,
            }

    track_ids = list(snapshot.track_meta)
    if track_ids:
        feature_rows = session.exec(
            select(TrackFeatures)
            .where(TrackFeatures.status == FeatureStatus.present)
            .where(col(TrackFeatures.track_id).in_(track_ids))
        ).all()
        for row in feature_rows:
            snapshot.features[row.track_id] = {
                feature: getattr(row, feature) for feature in CALIBRATED_FEATURES
            }
            snapshot.audio[row.track_id] = (row.tempo, row.key, row.mode)

    return snapshot


# Chunk size for IN(...) queries over track ids.
_IN_CHUNK = 400


def load_track_credits(session: Session, track_ids: list[int]) -> dict[int, list[str]]:
    """track id -> credited artist names, in credit order.

    LibrarySnapshot.track_meta keeps only the primary artist; the artist
    galaxy and genre frontier need every credit.
    """
    credits: dict[int, list[str]] = {}
    ids = sorted(track_ids)
    for start in range(0, len(ids), _IN_CHUNK):
        chunk = ids[start : start + _IN_CHUNK]
        for track in session.exec(select(Track).where(col(Track.id).in_(chunk))).all():
            assert track.id is not None
            credits[track.id] = [
                str(credit["name"]) for credit in track.artists if credit.get("name")
            ]
    return credits


# How many of the library's most-common ENAO genres form the genre-vector
# dimensions. A cap keeps the blended matrix small; the long tail of rare
# genres carries little clustering signal and would only add sparse noise.
GENRE_VECTOR_DIMS = 24

# How strongly the (L2-normalized) per-track genre block weighs against the
# acoustic percentile block in the clustering distance. Each acoustic axis has
# unit-ish spread in [0,1]; a track's genre vector is a unit vector, so this
# scale sets genre's pull relative to the ~8 acoustic axes. 2.0 lets genre carve
# legible ("this is my afrobeats corner") clusters without overwhelming acoustics.
GENRE_CLUSTER_WEIGHT = 2.0


def load_genre_vectors(
    session: Session, track_ids: list[int], *, dims: int = GENRE_VECTOR_DIMS
) -> tuple[dict[int, np.ndarray], list[str]]:
    """Per-track genre vector over the library's top-``dims`` ENAO genres.

    Joins each track's credited artists (casefolded name — the ENAO dump has no
    Spotify artist ids, so name is the working key, as radio/insights do) to
    ``ArtistGenre`` weights, sums per genre per track, restricts to the ``dims``
    genres with the most total library weight, and L2-normalizes each track's
    vector so genre contributes a bounded, comparable block regardless of how
    many genres a track's artists span. Tracks with no genre data get a zero
    vector (they simply don't move in the genre subspace).

    Returns (track id -> vector aligned to ``genres``, the ordered genre names).
    """
    if not track_ids:
        return {}, []

    # track id -> casefolded artist keys
    track_artist_keys: dict[int, set[str]] = {}
    all_keys: set[str] = set()
    ids = sorted(track_ids)
    for start in range(0, len(ids), _IN_CHUNK):
        chunk = ids[start : start + _IN_CHUNK]
        for track in session.exec(select(Track).where(col(Track.id).in_(chunk))).all():
            assert track.id is not None
            keys = {
                str(credit["name"]).casefold() for credit in track.artists if credit.get("name")
            }
            track_artist_keys[track.id] = keys
            all_keys |= keys

    if not all_keys:
        return {tid: np.zeros(0, dtype=float) for tid in track_ids}, []

    # genre name -> {artist key -> weight}, for artists the library actually holds.
    genre_by_id = {g.id: g.name for g in session.exec(select(Genre)).all() if g.id is not None}
    artist_genre_weights: dict[str, list[tuple[str, float]]] = {}
    genre_total: dict[str, float] = {}
    ordered_keys = sorted(all_keys)
    for start in range(0, len(ordered_keys), _IN_CHUNK):
        chunk = ordered_keys[start : start + _IN_CHUNK]
        rows = session.exec(
            select(ArtistGenre.genre_id, ArtistGenre.artist_name, ArtistGenre.weight).where(
                func.lower(ArtistGenre.artist_name).in_(chunk)
            )
        ).all()
        for genre_id, artist_name, weight in rows:
            name = genre_by_id.get(genre_id)
            if name is None:
                continue
            key = artist_name.casefold()
            artist_genre_weights.setdefault(key, []).append((name, float(weight or 0.0)))
            genre_total[name] = genre_total.get(name, 0.0) + float(weight or 0.0)

    if not genre_total:
        return {tid: np.zeros(0, dtype=float) for tid in track_ids}, []

    top_genres = [name for name, _ in sorted(genre_total.items(), key=lambda kv: (-kv[1], kv[0]))][
        :dims
    ]
    index = {name: i for i, name in enumerate(top_genres)}

    vectors: dict[int, np.ndarray] = {}
    for tid in track_ids:
        vec = np.zeros(len(top_genres), dtype=float)
        for key in track_artist_keys.get(tid, ()):  # type: ignore[union-attr]
            for name, weight in artist_genre_weights.get(key, ()):  # type: ignore[union-attr]
                pos = index.get(name)
                if pos is not None:
                    vec[pos] += weight
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        vectors[tid] = vec
    return vectors, top_genres


def load_percentile_space(session: Session) -> PercentileSpace:
    """Percentile space fitted on every enriched track in the catalog.

    The whole catalog (not one playlist) is the ranking population — a track
    is 'high energy' relative to everything the library knows.
    """
    rows = session.exec(
        select(TrackFeatures).where(TrackFeatures.status == FeatureStatus.present)
    ).all()
    library: dict[str, list[float]] = {feature: [] for feature in CALIBRATED_FEATURES}
    for row in rows:
        for feature in CALIBRATED_FEATURES:
            value = getattr(row, feature)
            if value is not None:
                library[feature].append(value)
    return PercentileSpace(library)
