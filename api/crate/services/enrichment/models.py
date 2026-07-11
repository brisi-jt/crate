"""Typed views over enrichment-source responses (extra keys ignored)."""

from pydantic import BaseModel, ConfigDict, Field


class AudioFeatures(BaseModel):
    """One track's audio features as returned by ReccoBeats or FreqBlog."""

    model_config = ConfigDict(extra="ignore")

    href: str | None = None
    isrc: str | None = None
    acousticness: float | None = None
    danceability: float | None = None
    energy: float | None = None
    instrumentalness: float | None = None
    key: int | None = None
    liveness: float | None = None
    loudness: float | None = None
    mode: int | None = None
    speechiness: float | None = None
    tempo: float | None = None
    valence: float | None = None


class SimilarArtist(BaseModel):
    """One entry from Last.fm artist.getSimilar."""

    model_config = ConfigDict(extra="ignore")

    name: str
    mbid: str | None = None
    match: float = 0.0


class ArtistTagView(BaseModel):
    """One entry from Last.fm getTopTags (artist or track)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    count: float = 0.0


class IsrcRecording(BaseModel):
    """MusicBrainz recording resolved from an ISRC, with its credited artists."""

    recording_mbid: str
    # (artist name, artist mbid) pairs in credit order.
    artist_credits: list[tuple[str, str]] = Field(default_factory=list)
