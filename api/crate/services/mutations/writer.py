"""The write surface a mutation needs from Spotify.

MutationService talks to this protocol; production adapts SpotifyClient,
tests substitute an in-memory state machine, and CRATE_FAKE_SPOTIFY demo mode
substitutes a database-backed stand-in.
"""

from typing import Protocol

from crate.services.spotify.client import SpotifyClient


class SpotifyWriter(Protocol):
    async def list_track_uris(self, playlist_spotify_id: str) -> list[str]: ...

    async def add_tracks(
        self, playlist_spotify_id: str, uris: list[str], position: int | None = None
    ) -> str: ...

    async def remove_tracks(self, playlist_spotify_id: str, uris: list[str]) -> str: ...

    async def reorder_range(
        self,
        playlist_spotify_id: str,
        range_start: int,
        insert_before: int,
        range_length: int = 1,
    ) -> str: ...

    async def create_playlist(
        self, name: str, description: str | None = None
    ) -> tuple[str, str]: ...

    async def change_details(
        self,
        playlist_spotify_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None: ...

    async def unfollow_playlist(self, playlist_spotify_id: str) -> None: ...

    async def add_saved_tracks(self, track_spotify_ids: list[str]) -> None: ...

    async def remove_saved_tracks(self, track_spotify_ids: list[str]) -> None: ...


class ClientWriter:
    """SpotifyWriter over the real API client."""

    def __init__(self, client: SpotifyClient) -> None:
        self._client = client

    async def list_track_uris(self, playlist_spotify_id: str) -> list[str]:
        return await self._client.list_track_uris(playlist_spotify_id)

    async def add_tracks(
        self, playlist_spotify_id: str, uris: list[str], position: int | None = None
    ) -> str:
        return await self._client.add_playlist_tracks(playlist_spotify_id, uris, position)

    async def remove_tracks(self, playlist_spotify_id: str, uris: list[str]) -> str:
        return await self._client.remove_playlist_tracks(playlist_spotify_id, uris)

    async def reorder_range(
        self,
        playlist_spotify_id: str,
        range_start: int,
        insert_before: int,
        range_length: int = 1,
    ) -> str:
        return await self._client.reorder_playlist_range(
            playlist_spotify_id,
            range_start=range_start,
            insert_before=insert_before,
            range_length=range_length,
        )

    async def create_playlist(self, name: str, description: str | None = None) -> tuple[str, str]:
        return await self._client.create_playlist(name, description)

    async def change_details(
        self,
        playlist_spotify_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        await self._client.change_playlist_details(
            playlist_spotify_id, name=name, description=description
        )

    async def unfollow_playlist(self, playlist_spotify_id: str) -> None:
        await self._client.unfollow_playlist(playlist_spotify_id)

    async def add_saved_tracks(self, track_spotify_ids: list[str]) -> None:
        await self._client.add_saved_tracks(track_spotify_ids)

    async def remove_saved_tracks(self, track_spotify_ids: list[str]) -> None:
        await self._client.remove_saved_tracks(track_spotify_ids)
