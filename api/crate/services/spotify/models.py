"""Typed views over Spotify Web API responses.

Only the fields crate consumes are modeled; unknown keys are ignored, so
payload additions on Spotify's side never break parsing.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    """One entry of a playlist's track listing.

    `/playlists/{id}/items` responses key the entry on `item` and keep
    `track` only as a deprecated alias; the older `/tracks` responses carry
    `track` alone. Both shapes normalize onto `track`, `item` winning when
    present.
    """

    added_at: datetime | None = None
    # Null when the track has been removed from the catalog.
    track: SpotifyTrack | None = None

    @model_validator(mode="before")
    @classmethod
    def _prefer_item_key(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("item") is not None:
            data = {**data, "track": data["item"]}
        return data


class SavedTrackItem(BaseModel):
    """One entry of the user's saved-tracks (Liked Songs) listing."""

    added_at: datetime | None = None
    track: SpotifyTrack


class PlayContext(BaseModel):
    """Where a play happened — playlist, album, artist or show."""

    type: str | None = None
    uri: str | None = None


class PlayHistoryItem(BaseModel):
    """One play from the recently-played history."""

    played_at: datetime
    track: SpotifyTrack
    context: PlayContext | None = None


class SpotifyTopArtist(BaseModel):
    """Artist as ranked by the top-items endpoint."""

    id: str
    name: str
    genres: list[str] = Field(default_factory=list)


class SpotifyOwner(BaseModel):
    id: str
    display_name: str | None = None


class SpotifyTracksRef(BaseModel):
    total: int = 0


class SpotifyPlaylistSummary(BaseModel):
    """Playlist as returned by GET /me/playlists (no track listing).

    The `/items` reshape reframes the entry-count ref from `tracks` to
    `items`; both shapes normalize onto `tracks`, `items` winning when
    present.
    """

    id: str
    name: str
    description: str | None = None
    snapshot_id: str
    owner: SpotifyOwner | None = None
    tracks: SpotifyTracksRef = Field(default_factory=SpotifyTracksRef)

    @model_validator(mode="before")
    @classmethod
    def _prefer_items_ref(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            data = {**data, "tracks": data["items"]}
        return data


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
