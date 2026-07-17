"""Score one triage track against every owned playlist.

The existing discovery machinery scores candidates against ONE playlist. Triage
inverts it: score one track against ALL owned playlists. The library loads once,
every owned-playlist centroid is precomputed once (never per track), and the
filed track is transformed into the same percentile space. Four signals are
computed per playlist and returned as four separately-labeled Evidence rows —
never a blended score:

- sonic_fit         proximity to the playlist centroid in percentile space,
                    plus which axes agree.
- artist_overlap    how many of the filed track's artists are already here.
- placement_history where the filed track's nearest already-filed neighbours
                    (in feature space) ended up.
- vibe_match        playlist name/description tokens vs the track's genre tokens.

All scoring is in percentile space — never raw/Spotify-era thresholds.
"""

from collections import Counter
from dataclasses import dataclass

from sqlmodel import Session, col, func, select

from crate.model.enums import EvidenceKind
from crate.model.orm import ArtistGenre, Genre, Playlist, Track, TrackFeatures, User
from crate.services.analytics.loaders import load_library, load_percentile_space
from crate.services.analytics.percentiles import PercentileSpace
from crate.services.discovery.ranker import NEUTRAL_RANK, _proximity
from crate.services.triage.evidence import DestinationSuggestion, Evidence
from crate.services.triage.tokenize import vibe_overlap

# How the four signals combine into the ordering rank. Sonic fit dominates;
# the others season. This is ORDER-ONLY — the evidence rows carry the story.
_RANK_WEIGHTS = {
    EvidenceKind.sonic_fit: 0.45,
    EvidenceKind.artist_overlap: 0.25,
    EvidenceKind.placement_history: 0.15,
    EvidenceKind.vibe_match: 0.15,
}

# Feature-space neighbours within this percentile distance count as "tracks
# like this" for placement history.
_NEIGHBOUR_RADIUS = 0.25


@dataclass
class _Centroids:
    space: PercentileSpace
    by_playlist: dict[int, dict[str, float]]
    vectors: dict[int, dict[str, float]]


def _precompute_centroids(session: Session, user: User) -> _Centroids:
    space = load_percentile_space(session)
    assert user.id is not None
    library = load_library(session, user.id)
    vectors = {tid: space.transform(values) for tid, values in library.features.items()}
    by_playlist: dict[int, dict[str, float]] = {}
    for playlist_id, members in library.memberships.items():
        member_vectors = [vectors[t] for t in sorted(members) if t in vectors]
        if not member_vectors:
            by_playlist[playlist_id] = {}
            continue
        by_playlist[playlist_id] = {
            feature: sum(v[feature] for v in member_vectors) / len(member_vectors)
            for feature in space.features
        }
    return _Centroids(space=space, by_playlist=by_playlist, vectors=vectors)


def _track_vector(session: Session, space: PercentileSpace, track_id: int) -> dict[str, float]:
    row = session.exec(select(TrackFeatures).where(TrackFeatures.track_id == track_id)).first()
    if row is None:
        return {}
    from crate.services.enrichment.calibration import CALIBRATED_FEATURES

    return space.transform({feature: getattr(row, feature) for feature in CALIBRATED_FEATURES})


def _track_artist_names(track: Track) -> list[str]:
    return [str(c["name"]) for c in track.artists if c.get("name")]


def _genre_tokens(session: Session, artist_names: list[str]) -> list[str]:
    if not artist_names:
        return []
    keys = [n.casefold() for n in artist_names]
    rows = session.exec(
        select(Genre.name)
        .join(ArtistGenre, ArtistGenre.genre_id == Genre.id)  # type: ignore[arg-type]
        .where(func.lower(ArtistGenre.artist_name).in_(keys))
    ).all()
    return list(dict.fromkeys(rows))


def suggest_destinations(
    session: Session, user: User, track_id: int
) -> list[DestinationSuggestion]:
    """Ranked destination suggestions for one track — four evidence rows each."""
    track = session.get(Track, track_id)
    if track is None:
        return []
    assert user.id is not None

    centroids = _precompute_centroids(session, user)
    vector = _track_vector(session, centroids.space, track_id)
    artist_names = _track_artist_names(track)
    artist_keys = {n.casefold() for n in artist_names}
    genres = _genre_tokens(session, artist_names)

    # Placement history: destinations of feature-space neighbours (already-filed
    # tracks close to this one). Precomputed once from the library vectors.
    neighbour_destinations = _placement_history_counts(session, user, centroids, vector, track_id)

    playlists = session.exec(
        select(Playlist)
        .where(Playlist.user_id == user.id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
        .where(Playlist.is_owned == True)  # noqa: E712 — SQL expression
    ).all()

    suggestions: list[DestinationSuggestion] = []
    for playlist in playlists:
        assert playlist.id is not None
        centroid = centroids.by_playlist.get(playlist.id, {})
        sonic = _sonic_fit_evidence(vector, centroid)
        overlap = _artist_overlap_evidence(session, playlist.id, artist_keys, artist_names)
        placement = _placement_evidence(neighbour_destinations, playlist.id)
        vibe = _vibe_evidence(playlist, genres)
        evidence = [sonic, overlap, placement, vibe]
        rank = sum(_RANK_WEIGHTS[e.kind] * e.score for e in evidence)
        already_in = _is_member(session, playlist.id, track_id)
        suggestions.append(
            DestinationSuggestion(
                playlist_id=playlist.id,
                name=playlist.name,
                rank=min(1.0, max(0.0, rank)),
                already_in=already_in,
                evidence=evidence,
            )
        )
    suggestions.sort(key=lambda s: (-s.rank, s.playlist_id))
    return suggestions


# -- per-signal scorers --------------------------------------------------------


def _sonic_fit_evidence(vector: dict[str, float], centroid: dict[str, float]) -> Evidence:
    score = _proximity(vector, centroid) if vector and centroid else NEUTRAL_RANK
    # Which axes agree (both above or both below the library median).
    agreeing = sorted(
        feature
        for feature, target in centroid.items()
        if feature in vector
        and (vector[feature] - 0.5) * (target - 0.5) > 0
        and abs(vector[feature] - target) < 0.2
    )
    if not vector:
        summary = "No audio features yet — neutral sonic fit."
    elif agreeing:
        summary = f"Similar {', '.join(agreeing[:3])} to this playlist's tracks."
    else:
        summary = "Sonic profile differs from this playlist."
    return Evidence(
        kind=EvidenceKind.sonic_fit,
        score=round(score, 4),
        summary=summary,
        detail={"agreeing_axes": agreeing},
    )


def _artist_overlap_evidence(
    session: Session, playlist_id: int, artist_keys: set[str], artist_names: list[str]
) -> Evidence:
    if not artist_keys:
        return Evidence(
            kind=EvidenceKind.artist_overlap, score=0.0, summary="No artist credits.", detail={}
        )
    from crate.model.orm import PlaylistTrack

    tracks = session.exec(
        select(Track)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.playlist_id == playlist_id)
    ).all()
    count = 0
    for member in tracks:
        for credit in member.artists:
            if str(credit.get("name", "")).casefold() in artist_keys:
                count += 1
                break
    # Saturating: a handful of same-artist tracks is a strong signal.
    score = min(1.0, count / 4.0)
    name = artist_names[0] if artist_names else "this artist"
    summary = (
        f"{count} track{'s' if count != 1 else ''} by {name} already here."
        if count
        else f"No tracks by {name} here yet."
    )
    return Evidence(
        kind=EvidenceKind.artist_overlap,
        score=round(score, 4),
        summary=summary,
        detail={"count": count},
    )


def _placement_history_counts(
    session: Session, user: User, centroids: _Centroids, vector: dict[str, float], track_id: int
) -> Counter[int]:
    """Playlist -> how many feature-space neighbours of the filed track live there."""
    counts: Counter[int] = Counter()
    if not vector:
        return counts
    from crate.model.orm import PlaylistTrack

    neighbour_ids = [
        tid
        for tid, v in centroids.vectors.items()
        if tid != track_id and _proximity(vector, v) >= (1.0 - _NEIGHBOUR_RADIUS)
    ]
    if not neighbour_ids:
        return counts
    rows = session.exec(
        select(PlaylistTrack.playlist_id)
        .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user.id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
        .where(col(PlaylistTrack.track_id).in_(neighbour_ids))
    ).all()
    counts.update(rows)
    return counts


def _placement_evidence(neighbour_destinations: Counter[int], playlist_id: int) -> Evidence:
    total = sum(neighbour_destinations.values())
    here = neighbour_destinations.get(playlist_id, 0)
    score = (here / total) if total else 0.0
    summary = (
        f"{here} track{'s' if here != 1 else ''} like this ended up here."
        if here
        else "Tracks like this rarely land here."
    )
    return Evidence(
        kind=EvidenceKind.placement_history,
        score=round(min(1.0, score), 4),
        summary=summary,
        detail={"neighbours_here": here, "neighbours_total": total},
    )


def _vibe_evidence(playlist: Playlist, genres: list[str]) -> Evidence:
    overlap = vibe_overlap(playlist.name, playlist.description, genres)
    if overlap.matched:
        summary = f"Name/genre match: {', '.join(sorted(overlap.matched)[:3])}."
    else:
        summary = "No name/genre overlap."
    return Evidence(
        kind=EvidenceKind.vibe_match,
        score=round(min(1.0, overlap.score), 4),
        summary=summary,
        detail={"matched": sorted(overlap.matched)},
    )


def _is_member(session: Session, playlist_id: int, track_id: int) -> bool:
    from crate.model.orm import PlaylistTrack

    return (
        session.exec(
            select(PlaylistTrack.id)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .where(PlaylistTrack.track_id == track_id)
        ).first()
        is not None
    )
