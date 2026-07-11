"""Typed views over Spotify Web API responses.

Only the fields crate consumes are modeled; unknown keys are ignored, so
payload additions on Spotify's side never break parsing.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SpotifyExternalIds(BaseModel):
    isrc: str | None = None


class SpotifyArtistRef(BaseModel):
    # Both null for local files.
    id: str | None = None
    name: str | None = None


class SpotifyAlbumRef(BaseModel):
    id: str | None = None
    name: str | None = None


class SpotifyTrack(BaseModel):
    # Null for local files (which crate skips).
    id: str | None = None
    name: str
    duration_ms: int | None = None
    is_local: bool = False
    external_ids: SpotifyExternalIds = Field(default_factory=SpotifyExternalIds)
    artists: list[SpotifyArtistRef] = Field(default_factory=list)
    album: SpotifyAlbumRef | None = None


class PlaylistTrackItem(BaseModel):
    """One entry of a playlist's track listing."""

    added_at: datetime | None = None
    # Null when the track has been removed from the catalog.
    track: SpotifyTrack | None = None


class SpotifyOwner(BaseModel):
    id: str
    display_name: str | None = None


class SpotifyTracksRef(BaseModel):
    total: int = 0


class SpotifyPlaylistSummary(BaseModel):
    """Playlist as returned by GET /me/playlists (no track listing)."""

    id: str
    name: str
    description: str | None = None
    snapshot_id: str
    owner: SpotifyOwner | None = None
    tracks: SpotifyTracksRef = Field(default_factory=SpotifyTracksRef)


class SpotifyUser(BaseModel):
    id: str
    display_name: str | None = None


class TokenResponse(BaseModel):
    """Body of the accounts-service token endpoint (exchange and refresh)."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    # Refresh responses may omit this, meaning the old refresh token stays valid.
    refresh_token: str | None = None
    scope: str | None = None
