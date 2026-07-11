"""Top-items snapshot capture.

One pass writes six immutable rows — artist/track rankings for each of
Spotify's three affinity windows — all sharing a captured_at, so history
accumulates and trends can be diffed between passes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlmodel import Session

from crate.model.enums import TopItemKind, TopTimeRange
from crate.model.orm import TopItemsSnapshot, User, utcnow


class TopItemsReader(Protocol):
    """Read surface of SpotifyClient the snapshot capture depends on."""

    async def get_top_artists(
        self, time_range: str = "medium_term", limit: int = 50
    ): ...  # list[SpotifyTopArtist]

    async def get_top_tracks(
        self, time_range: str = "medium_term", limit: int = 50
    ): ...  # list[SpotifyTrack]


@dataclass
class TopItemsReport:
    """Counts from one snapshot pass."""

    snapshots: int = 0
    captured_at: datetime = field(default_factory=utcnow)


_SPOTIFY_RANGES: dict[TopTimeRange, str] = {
    TopTimeRange.short: "short_term",
    TopTimeRange.medium: "medium_term",
    TopTimeRange.long: "long_term",
}


async def capture_top_items(
    session: Session, spotify: TopItemsReader, user: User
) -> TopItemsReport:
    report = TopItemsReport(captured_at=utcnow())

    for time_range, spotify_range in _SPOTIFY_RANGES.items():
        artists = await spotify.get_top_artists(time_range=spotify_range, limit=50)
        artist_items: list[dict[str, Any]] = [
            {"rank": rank, "spotify_id": artist.id, "name": artist.name}
            for rank, artist in enumerate(artists, start=1)
        ]
        session.add(
            TopItemsSnapshot(
                user_id=user.id,
                kind=TopItemKind.artist,
                time_range=time_range,
                captured_at=report.captured_at,
                items=artist_items,
            )
        )
        report.snapshots += 1

        tracks = await spotify.get_top_tracks(time_range=spotify_range, limit=50)
        track_items: list[dict[str, Any]] = [
            {
                "rank": rank,
                "spotify_id": track.id,
                "name": track.name,
                "artists": [artist.name for artist in track.artists if artist.name],
            }
            for rank, track in enumerate(tracks, start=1)
            if track.id is not None
        ]
        session.add(
            TopItemsSnapshot(
                user_id=user.id,
                kind=TopItemKind.track,
                time_range=time_range,
                captured_at=report.captured_at,
                items=track_items,
            )
        )
        report.snapshots += 1

    session.commit()
    return report
