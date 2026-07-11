"""Database -> plain-structure loaders for the analytics engine.

The metric modules are pure functions over sets, dicts, and numpy arrays;
everything ORM-shaped stays in here.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, col, select

from crate.model.enums import FeatureStatus
from crate.model.orm import Playlist, PlaylistTrack, Track, TrackFeatures
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
    # track id -> {"spotify_id", "isrc", "name", "artist"}
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
