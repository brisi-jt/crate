"""In-memory stand-ins for the discovery pipeline's external sources."""

from datetime import datetime

from sqlmodel import Session, select

from crate.model.enums import PlaylistSyncStatus
from crate.model.orm import Playlist, PlaylistTrack, Track, TrackFeatures, User
from crate.services.enrichment.models import (
    ArtistTopTrack,
    AudioFeatures,
    DeezerTrack,
    RecommendedTrack,
    SimilarArtist,
)
from crate.services.spotify.models import SpotifyTrack


class FakeLastFm:
    """Similar artists + top tracks from dictionaries."""

    def __init__(
        self,
        similar: dict[str, list[SimilarArtist]] | None = None,
        top_tracks: dict[str, list[ArtistTopTrack]] | None = None,
    ) -> None:
        self.similar = similar or {}
        self.top_tracks = top_tracks or {}
        self.calls: list[tuple[str, str]] = []

    async def get_similar_artists(self, artist_name: str) -> list[SimilarArtist]:
        self.calls.append(("similar", artist_name))
        return self.similar.get(artist_name, [])

    async def get_artist_top_tracks(
        self, artist_name: str, limit: int = 10
    ) -> list[ArtistTopTrack]:
        self.calls.append(("top_tracks", artist_name))
        return self.top_tracks.get(artist_name, [])[:limit]


class FakeRecco:
    """Recommendations + audio features from dictionaries."""

    def __init__(
        self,
        recommendations: list[RecommendedTrack] | None = None,
        features: dict[str, AudioFeatures] | None = None,
    ) -> None:
        self.recommendations = recommendations or []
        self.features = features or {}
        self.seed_calls: list[list[str]] = []

    async def get_track_recommendation(
        self, seed_spotify_ids: list[str], size: int = 20
    ) -> list[RecommendedTrack]:
        self.seed_calls.append(seed_spotify_ids)
        return self.recommendations[:size]

    async def get_audio_features_batch(self, spotify_ids: list[str]) -> dict[str, AudioFeatures]:
        return {sid: self.features[sid] for sid in spotify_ids if sid in self.features}


class FakeResolver:
    """search_tracks from a query -> results dictionary."""

    def __init__(self, results: dict[str, list[SpotifyTrack]] | None = None) -> None:
        self.results = results or {}
        self.queries: list[str] = []

    async def search_tracks(self, query: str, limit: int = 5) -> list[SpotifyTrack]:
        self.queries.append(query)
        return self.results.get(query, [])[:limit]


class FakeDeezer:
    def __init__(self, previews: dict[str, str] | None = None) -> None:
        # "title|artist" (lowercased) -> preview URL
        self.previews = previews or {}
        self.queries: list[tuple[str, str]] = []

    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None:
        self.queries.append((title, artist))
        url = self.previews.get(f"{title.lower()}|{artist.lower()}")
        if url is None:
            return None
        return DeezerTrack(id=1, title=title, preview=url, artist_name=artist)


def recommended(
    title: str, artist: str, spotify_id: str, isrc: str | None = None
) -> RecommendedTrack:
    return RecommendedTrack.model_validate(
        {
            "id": f"rb-{spotify_id}",
            "trackTitle": title,
            "href": f"https://open.spotify.com/track/{spotify_id}",
            "isrc": isrc,
            "durationMs": 200_000,
            "artists": [{"id": f"rb-a-{artist}", "name": artist}],
        }
    )


def seed_playlist(
    session: Session,
    user: User,
    name: str,
    tracks: list[tuple[str, str, str]],
    features: dict[str, dict[str, float]] | None = None,
) -> Playlist:
    """Playlist with (spotify_id, title, artist) tracks and optional features."""
    playlist = Playlist(
        user_id=user.id,
        spotify_id=f"pl-{name.lower().replace(' ', '-')}",
        name=name,
        snapshot_id=f"snap-{name}",
        status=PlaylistSyncStatus.synced,
    )
    session.add(playlist)
    session.flush()
    for position, (spotify_id, title, artist) in enumerate(tracks):
        track = session.exec(select(Track).where(Track.spotify_id == spotify_id)).first()
        if track is None:
            track = Track(
                spotify_id=spotify_id,
                isrc=f"IS{spotify_id[:10].upper()}",
                name=title,
                artists=[{"spotify_id": f"a-{artist}", "name": artist}],
                album_name=f"{title} LP",
                duration_ms=210_000,
            )
            session.add(track)
            session.flush()
            values = (features or {}).get(spotify_id)
            if values is not None:
                session.add(TrackFeatures(track_id=track.id, **values))
        session.add(
            PlaylistTrack(
                user_id=user.id,
                playlist_id=playlist.id,
                track_id=track.id,
                position=position,
                added_at=datetime(2025, 1, 1),
            )
        )
    session.commit()
    session.refresh(playlist)
    return playlist
