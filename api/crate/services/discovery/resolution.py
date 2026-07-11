"""Candidate resolution: Spotify match, audio features, preview audio.

Resolution turns a (title, artist) proposal into a playable, addable track:

1. Spotify search — by ISRC when the candidate carries one (exact identity),
   falling back to a quoted track+artist query. No match marks the candidate
   unresolvable, permanently.
2. Audio features — ReccoBeats, batched; ranked against the library's
   percentile space at queue-build time.
3. Preview audio — Deezer 30-second URL, matched by artist so a cover can
   never play in place of the real track.
"""

import hashlib
from typing import Protocol

from sqlmodel import Session

from crate.model.enums import CandidateStatus
from crate.model.orm import DiscoveryCandidate
from crate.services.enrichment.models import AudioFeatures, DeezerTrack
from crate.services.spotify.models import SpotifyArtistRef, SpotifyExternalIds, SpotifyTrack

# The feature keys persisted onto a candidate (raw values, ReccoBeats scale).
CANDIDATE_FEATURE_KEYS = (
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


class TrackSearch(Protocol):
    async def search_tracks(self, query: str, limit: int = 5) -> list[SpotifyTrack]: ...


class FeatureSource(Protocol):
    async def get_audio_features_batch(
        self, spotify_ids: list[str]
    ) -> dict[str, AudioFeatures]: ...


class PreviewSource(Protocol):
    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None: ...


class FakeSpotifyResolver:
    """Stand-in resolver for CRATE_FAKE_SPOTIFY development mode.

    Every query resolves to one invented track whose ID is a stable hash of
    the query, so the pipeline behaves identically across runs without a
    Spotify credential.
    """

    async def search_tracks(self, query: str, limit: int = 5) -> list[SpotifyTrack]:
        digest = hashlib.sha1(query.encode()).hexdigest()[:16]
        title, artist = _query_parts(query)
        return [
            SpotifyTrack(
                id=f"fake-{digest}",
                name=title or query,
                duration_ms=200_000,
                external_ids=SpotifyExternalIds(isrc=None),
                artists=[SpotifyArtistRef(id=None, name=artist or "Unknown")],
                album=None,
            )
        ]


def _query_parts(query: str) -> tuple[str | None, str | None]:
    """(title, artist) from a track:"..." artist:"..." query, when present."""
    title = artist = None
    if 'track:"' in query:
        title = query.split('track:"', 1)[1].split('"', 1)[0]
    if 'artist:"' in query:
        artist = query.split('artist:"', 1)[1].split('"', 1)[0]
    return title, artist


def _search_query(candidate: DiscoveryCandidate) -> str:
    return f'track:"{candidate.title}" artist:"{candidate.artist}"'


async def resolve_candidates(
    session: Session,
    candidates: list[DiscoveryCandidate],
    resolver: TrackSearch,
) -> int:
    """Match pending candidates to Spotify tracks. Returns the resolved count."""
    resolved = 0
    for candidate in candidates:
        if candidate.status != CandidateStatus.pending:
            continue
        match: SpotifyTrack | None = None
        if candidate.isrc:
            results = await resolver.search_tracks(f"isrc:{candidate.isrc}", limit=1)
            match = next((t for t in results if t.id), None)
        if match is None:
            results = await resolver.search_tracks(_search_query(candidate), limit=5)
            match = next((t for t in results if t.id), None)
        if match is None:
            candidate.status = CandidateStatus.unresolvable
            session.add(candidate)
            continue
        candidate.spotify_id = match.id
        if match.external_ids.isrc:
            candidate.isrc = match.external_ids.isrc
        if match.album is not None:
            candidate.album_name = match.album.name
        if match.duration_ms is not None:
            candidate.duration_ms = match.duration_ms
        candidate.status = CandidateStatus.resolved
        session.add(candidate)
        resolved += 1
    session.commit()
    return resolved


async def fetch_candidate_features(
    session: Session,
    candidates: list[DiscoveryCandidate],
    features_source: FeatureSource,
) -> int:
    """Attach raw audio features to resolved candidates that lack them."""
    wanting = [
        c
        for c in candidates
        if c.status == CandidateStatus.resolved and c.spotify_id and c.features is None
    ]
    if not wanting:
        return 0
    batch = await features_source.get_audio_features_batch(
        [c.spotify_id for c in wanting if c.spotify_id]
    )
    fetched = 0
    for candidate in wanting:
        values = batch.get(candidate.spotify_id or "")
        if values is None:
            continue
        candidate.features = {
            key: getattr(values, key)
            for key in CANDIDATE_FEATURE_KEYS
            if getattr(values, key) is not None
        }
        session.add(candidate)
        fetched += 1
    session.commit()
    return fetched


async def resolve_previews(
    session: Session,
    candidates: list[DiscoveryCandidate],
    previews: PreviewSource,
) -> int:
    """Fill Deezer preview URLs; a miss just leaves the candidate preview-less."""
    resolved = 0
    for candidate in candidates:
        if candidate.status != CandidateStatus.resolved or candidate.preview_url:
            continue
        result = await previews.search_preview(candidate.title, candidate.artist)
        if result is None:
            continue
        candidate.preview_url = result.preview
        session.add(candidate)
        resolved += 1
    session.commit()
    return resolved
