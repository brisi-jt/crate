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


class ArtistTopTrack(BaseModel):
    """One entry from Last.fm artist.getTopTracks."""

    model_config = ConfigDict(extra="ignore")

    name: str
    artist_name: str = ""
    mbid: str | None = None


class RecommendedTrack(BaseModel):
    """One entry from ReccoBeats track recommendation."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    title: str = Field(alias="trackTitle")
    href: str | None = None
    isrc: str | None = None
    duration_ms: int | None = Field(default=None, alias="durationMs")
    artists: list[dict] = Field(default_factory=list)

    @property
    def spotify_id(self) -> str | None:
        """ReccoBeats hrefs are open.spotify.com track URLs; the ID is the last segment."""
        if not self.href:
            return None
        return self.href.rstrip("/").rsplit("/", 1)[-1] or None

    @property
    def artist_names(self) -> list[str]:
        return [str(a["name"]) for a in self.artists if a.get("name")]


class DeezerTrack(BaseModel):
    """One Deezer search result carrying a 30-second preview."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    preview: str = ""
    isrc: str | None = None
    artist_name: str = ""


class IsrcRecording(BaseModel):
    """MusicBrainz recording resolved from an ISRC, with its credited artists."""

    recording_mbid: str
    # (artist name, artist mbid) pairs in credit order.
    artist_credits: list[tuple[str, str]] = Field(default_factory=list)


class ArtistSearchResult(BaseModel):
    """One candidate from a MusicBrainz artist name search."""

    model_config = ConfigDict(extra="ignore")

    mbid: str = Field(alias="id")
    name: str
    # MusicBrainz relevance score, 0-100 (100 = exact).
    score: int = 0
