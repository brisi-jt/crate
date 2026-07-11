"""Candidate generation for one playlist.

Two sources feed the pool:

- Last.fm: similar artists of the playlist's most-played artists, then those
  artists' top tracks. Skipped (never errored) when no API key is configured.
- ReccoBeats: track recommendations seeded by the playlist's opening tracks.
  These arrive with Spotify links, so they start life already resolved.

The exclusion rule is absolute: a candidate is dropped when its Spotify ID,
ISRC, or title+artist already exists anywhere in the user's library, when the
user has previously rejected it (any playlist), or when it has already been
proposed for this playlist.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session, col, select

from crate.model.enums import CandidateSource, CandidateStatus
from crate.model.orm import (
    ArtistGenre,
    DiscoveryCandidate,
    Genre,
    Playlist,
    PlaylistTrack,
    Track,
    User,
)
from crate.services.enrichment.models import ArtistTopTrack, RecommendedTrack, SimilarArtist

# How wide the generation pass fans out. Small numbers keep one pass inside
# polite rate limits (each similar-artist lookup is a paced Last.fm call).
TOP_ARTISTS_PER_PLAYLIST = 5
SIMILAR_PER_ARTIST = 5
TRACKS_PER_SIMILAR_ARTIST = 3
RECOMMENDATION_SIZE = 20
EXEMPLAR_SEEDS = 5
DEFAULT_CANDIDATE_LIMIT = 50

# Genre-seeded runs: how many of the genre's defining artists to walk, and
# how many tracks each contributes.
GENRE_EXEMPLAR_ARTISTS = 8
TRACKS_PER_GENRE_ARTIST = 3


class SimilarArtistSource(Protocol):
    async def get_similar_artists(self, artist_name: str) -> list[SimilarArtist]: ...

    async def get_artist_top_tracks(
        self, artist_name: str, limit: int = 10
    ) -> list[ArtistTopTrack]: ...


class RecommendationSource(Protocol):
    async def get_track_recommendation(
        self, seed_spotify_ids: list[str], size: int = 20
    ) -> list[RecommendedTrack]: ...


class ArtistTrackSource(Protocol):
    """Anything that can name an artist's best-known tracks."""

    async def get_artist_top_tracks(
        self, artist_name: str, limit: int = 10
    ) -> list[ArtistTopTrack]: ...


@dataclass
class GenerationReport:
    """Counts from one generation pass over one playlist."""

    generated_lastfm: int = 0
    generated_reccobeats: int = 0
    generated_enao: int = 0
    excluded: int = 0
    lastfm_skipped: bool = False


def dedup_key(title: str, artist: str) -> str:
    """Case-folded track identity — one proposal per track per playlist."""
    return f"{artist.strip().casefold()}|{title.strip().casefold()}"[:255]


@dataclass
class _LibraryIndex:
    """Identity sets a candidate must not collide with."""

    spotify_ids: set[str]
    isrcs: set[str]
    track_keys: set[str]
    barred_keys: set[str]  # rejected anywhere, or already proposed here
    artist_keys: set[str]  # casefolded credited artist names in the library


def _load_index(session: Session, user: User, playlist: Playlist) -> _LibraryIndex:
    library_tracks = session.exec(
        select(Track)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user.id)
    ).all()
    track_keys = set()
    artist_keys = set()
    for track in library_tracks:
        for credit in track.artists:
            name = credit.get("name")
            if name:
                track_keys.add(dedup_key(track.name, str(name)))
                artist_keys.add(str(name).casefold())

    existing = session.exec(
        select(DiscoveryCandidate).where(DiscoveryCandidate.user_id == user.id)
    ).all()
    barred = {c.dedup_key for c in existing if c.playlist_id == playlist.id}
    barred |= {c.dedup_key for c in existing if c.status == CandidateStatus.rejected}

    return _LibraryIndex(
        spotify_ids={t.spotify_id for t in library_tracks},
        isrcs={t.isrc for t in library_tracks if t.isrc},
        track_keys=track_keys,
        barred_keys=barred,
        artist_keys=artist_keys,
    )


class _Admission:
    """Applies the exclusion rule and the per-pass limit for one playlist."""

    def __init__(
        self, session: Session, index: _LibraryIndex, report: GenerationReport, limit: int
    ) -> None:
        self._session = session
        self._index = index
        self._report = report
        self._limit = limit
        self._accepted = 0

    def _excluded(self, key: str, spotify_id: str | None, isrc: str | None) -> bool:
        index = self._index
        if key in index.track_keys or key in index.barred_keys:
            return True
        if spotify_id is not None and spotify_id in index.spotify_ids:
            return True
        return isrc is not None and isrc in index.isrcs

    def admit(self, candidate: DiscoveryCandidate) -> bool:
        if self._accepted >= self._limit:
            return False
        if self._excluded(candidate.dedup_key, candidate.spotify_id, candidate.isrc):
            self._report.excluded += 1
            return False
        self._session.add(candidate)
        self._index.barred_keys.add(candidate.dedup_key)
        if candidate.spotify_id:
            self._index.spotify_ids.add(candidate.spotify_id)
        if candidate.isrc:
            self._index.isrcs.add(candidate.isrc)
        self._accepted += 1
        return True


def playlist_top_artists(session: Session, playlist: Playlist) -> list[str]:
    """Most-credited artist names, ties broken alphabetically."""
    rows = session.exec(
        select(Track)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.playlist_id == playlist.id)
    ).all()
    counts: Counter[str] = Counter()
    for track in rows:
        for credit in track.artists:
            name = credit.get("name")
            if name:
                counts[str(name)] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, _ in ordered[:TOP_ARTISTS_PER_PLAYLIST]]


def _exemplar_seed_ids(session: Session, playlist: Playlist) -> list[str]:
    """Spotify IDs of the playlist's opening tracks — the recommendation seeds."""
    rows = session.exec(
        select(Track.spotify_id)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.playlist_id == playlist.id)
        .order_by(PlaylistTrack.position)  # type: ignore[arg-type]
    ).all()
    seeds: list[str] = []
    for spotify_id in rows:
        if spotify_id not in seeds:
            seeds.append(spotify_id)
        if len(seeds) == EXEMPLAR_SEEDS:
            break
    return seeds


async def generate_for_playlist(
    session: Session,
    user: User,
    playlist: Playlist,
    *,
    lastfm: SimilarArtistSource | None,
    reccobeats: RecommendationSource,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> GenerationReport:
    report = GenerationReport(lastfm_skipped=lastfm is None)
    admission = _Admission(session, _load_index(session, user, playlist), report, limit)
    admit = admission.admit

    if lastfm is not None:
        for seed_artist in playlist_top_artists(session, playlist):
            for similar in (await lastfm.get_similar_artists(seed_artist))[:SIMILAR_PER_ARTIST]:
                top_tracks = await lastfm.get_artist_top_tracks(
                    similar.name, limit=TRACKS_PER_SIMILAR_ARTIST
                )
                for track in top_tracks:
                    candidate = DiscoveryCandidate(
                        user_id=user.id,
                        playlist_id=playlist.id,
                        source=CandidateSource.lastfm,
                        status=CandidateStatus.pending,
                        title=track.name,
                        artist=track.artist_name or similar.name,
                        dedup_key=dedup_key(track.name, track.artist_name or similar.name),
                        seed_artist=seed_artist,
                    )
                    if admit(candidate):
                        report.generated_lastfm += 1

    seeds = _exemplar_seed_ids(session, playlist)
    if seeds:
        recommendations = await reccobeats.get_track_recommendation(seeds, size=RECOMMENDATION_SIZE)
        for recommendation in recommendations:
            artist = recommendation.artist_names[0] if recommendation.artist_names else ""
            candidate = DiscoveryCandidate(
                user_id=user.id,
                playlist_id=playlist.id,
                source=CandidateSource.reccobeats,
                # Recommendations link straight to Spotify tracks, so they
                # skip the search step entirely.
                status=(
                    CandidateStatus.resolved
                    if recommendation.spotify_id
                    else CandidateStatus.pending
                ),
                title=recommendation.title,
                artist=artist,
                dedup_key=dedup_key(recommendation.title, artist),
                spotify_id=recommendation.spotify_id,
                isrc=recommendation.isrc,
                duration_ms=recommendation.duration_ms,
            )
            if admit(candidate):
                report.generated_reccobeats += 1

    session.commit()
    return report


async def generate_from_genre(
    session: Session,
    user: User,
    playlist: Playlist,
    genre: Genre,
    *,
    tracks: ArtistTrackSource,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> GenerationReport:
    """Candidates from a genre's defining artists that the library lacks.

    The genre's strongest members (by ENAO weight) that are NOT already
    credited anywhere in the library are walked in order; each contributes
    its best-known tracks. The standard exclusion rule still applies to
    every proposed track.
    """
    report = GenerationReport()
    index = _load_index(session, user, playlist)
    admission = _Admission(session, index, report, limit)

    members = session.exec(
        select(ArtistGenre)
        .where(ArtistGenre.genre_id == genre.id)
        .order_by(col(ArtistGenre.weight).desc(), col(ArtistGenre.artist_name))
    ).all()
    exemplars = [
        row.artist_name for row in members if row.artist_name.casefold() not in index.artist_keys
    ][:GENRE_EXEMPLAR_ARTISTS]

    for artist_name in exemplars:
        top_tracks = await tracks.get_artist_top_tracks(artist_name, limit=TRACKS_PER_GENRE_ARTIST)
        for track in top_tracks:
            candidate = DiscoveryCandidate(
                user_id=user.id,
                playlist_id=playlist.id,
                source=CandidateSource.enao,
                status=CandidateStatus.pending,
                title=track.name,
                artist=track.artist_name or artist_name,
                dedup_key=dedup_key(track.name, track.artist_name or artist_name),
                seed_artist=artist_name,
            )
            if admission.admit(candidate):
                report.generated_enao += 1

    session.commit()
    return report
