"""In-memory Spotify write surface with real API semantics.

The fake mirrors Spotify's documented behavior exactly — remove deletes ALL
occurrences of a URI, reorder moves a range with insert-before indexing on the
pre-move list — so the property suite exercises the same state machine the
production client talks to.
"""

from dataclasses import dataclass, field

from crate.services.spotify.client import SpotifyApiError


@dataclass
class FakePlaylistState:
    name: str
    description: str | None = None
    uris: list[str] = field(default_factory=list)
    snapshot: str = "snap-0"
    followed: bool = True


def spotify_reorder(
    uris: list[str], range_start: int, insert_before: int, range_length: int = 1
) -> list[str]:
    """Spotify's reorder semantics: indices refer to the pre-move list."""
    chunk = uris[range_start : range_start + range_length]
    rest = uris[:range_start] + uris[range_start + range_length :]
    idx = insert_before - range_length if insert_before > range_start else insert_before
    return rest[:idx] + chunk + rest[idx:]


class FakeSpotify:
    """Implements the SpotifyWriter protocol over in-memory playlists."""

    def __init__(self) -> None:
        self.playlists: dict[str, FakePlaylistState] = {}
        self.write_calls: int = 0
        # Raise on write call number (1-based) > fail_after. None = never fail.
        self.fail_after: int | None = None
        self._snapshot_counter = 0
        self._playlist_counter = 0

    # -- test seeding ----------------------------------------------------

    def seed(self, spotify_id: str, name: str, uris: list[str]) -> None:
        self.playlists[spotify_id] = FakePlaylistState(name=name, uris=list(uris))

    def listing(self, spotify_id: str) -> list[str]:
        return list(self.playlists[spotify_id].uris)

    # -- internals ---------------------------------------------------------

    def _write(self) -> None:
        self.write_calls += 1
        if self.fail_after is not None and self.write_calls > self.fail_after:
            raise SpotifyApiError(500, "injected failure")

    def _bump(self, spotify_id: str) -> str:
        self._snapshot_counter += 1
        snapshot = f"snap-{self._snapshot_counter}"
        self.playlists[spotify_id].snapshot = snapshot
        return snapshot

    # -- SpotifyWriter protocol -------------------------------------------

    async def list_track_uris(self, playlist_spotify_id: str) -> list[str]:
        return list(self.playlists[playlist_spotify_id].uris)

    async def add_tracks(
        self, playlist_spotify_id: str, uris: list[str], position: int | None = None
    ) -> str:
        self._write()
        state = self.playlists[playlist_spotify_id]
        if position is None:
            state.uris.extend(uris)
        else:
            state.uris[position:position] = uris
        return self._bump(playlist_spotify_id)

    async def remove_tracks(self, playlist_spotify_id: str, uris: list[str]) -> str:
        self._write()
        state = self.playlists[playlist_spotify_id]
        drop = set(uris)
        state.uris = [u for u in state.uris if u not in drop]
        return self._bump(playlist_spotify_id)

    async def reorder_range(
        self,
        playlist_spotify_id: str,
        range_start: int,
        insert_before: int,
        range_length: int = 1,
    ) -> str:
        self._write()
        state = self.playlists[playlist_spotify_id]
        state.uris = spotify_reorder(state.uris, range_start, insert_before, range_length)
        return self._bump(playlist_spotify_id)

    async def create_playlist(self, name: str, description: str | None = None) -> tuple[str, str]:
        self._write()
        self._playlist_counter += 1
        spotify_id = f"fake-pl-{self._playlist_counter}"
        self.playlists[spotify_id] = FakePlaylistState(name=name, description=description)
        return spotify_id, self._bump(spotify_id)

    async def change_details(
        self,
        playlist_spotify_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        self._write()
        state = self.playlists[playlist_spotify_id]
        if name is not None:
            state.name = name
        if description is not None:
            state.description = description

    async def unfollow_playlist(self, playlist_spotify_id: str) -> None:
        self._write()
        if playlist_spotify_id in self.playlists:
            self.playlists[playlist_spotify_id].followed = False
