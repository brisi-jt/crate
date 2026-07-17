"""Typed views over Spotify Web API responses.

Only the fields crate consumes are modeled; unknown keys are ignored, so
payload additions on Spotify's side never break parsing.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SpotifyExternalIds(BaseModel):
    isrc: str | None = None


class SpotifyImage(BaseModel):
    """One image in a Spotify image set (cover art, artist photo, playlist cover)."""

    url: str
    height: int | None = None
    width: int | None = None


def largest_image_url(images: list[SpotifyImage]) -> str | None:
    """URL of the biggest image, by pixel area; None for an empty set.

    Spotify usually orders images largest-first, but that is not guaranteed —
    pick by area so the anchor is always the highest resolution available.
    """
    if not images:
        return None
    return max(images, key=_image_area).url


def smallest_image_url(images: list[SpotifyImage]) -> str | None:
    """URL of the smallest image, by pixel area; None for an empty set.

    The list thumb: never decode the full-size art for a hover card.
    """
    if not images:
        return None
    return min(images, key=_image_area).url


def _image_area(image: SpotifyImage) -> int:
    # Missing dimensions sort as unknown-largest so a sizeless entry never
    # wins the thumb slot; a fully sizeless set keeps its given order.
    if image.height is None or image.width is None:
        return 1 << 30
    return image.height * image.width


class SpotifyArtistRef(BaseModel):
    # Both null for local files. Track artist refs never carry images —
    # artist photos come from the full /v1/artists objects (SpotifyArtist).
    id: str | None = None
    name: str | None = None


class SpotifyArtist(BaseModel):
    """Full artist object from GET /v1/artists — carries the photo set."""

    id: str
    name: str
    images: list[SpotifyImage] = Field(default_factory=list)


class SpotifyAlbumRef(BaseModel):
    id: str | None = None
    name: str | None = None
    # Album art, present on the album object embedded in a track.
    images: list[SpotifyImage] = Field(default_factory=list)


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
    # Spotify's playlist cover set, when the playlist has one.
    images: list[SpotifyImage] = Field(default_factory=list)

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
