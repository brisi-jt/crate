"""Saved-tracks (Liked Songs) diff sync.

Walks the full remote library each pass and reconciles it against the stored
rows. Removals flip is_removed instead of deleting, so SavedTrack rows carry
the library's add/remove history (the saved-library counterpart of the
playlist-scoped SyncEvent trail).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlmodel import Session, select

from crate.model.orm import SavedTrack, Track, User, utcnow
from crate.services.spotify.models import SpotifyTrack
from crate.services.sync import _naive_utc, upsert_track


class SavedTracksReader(Protocol):
    """Read surface of SpotifyClient the saved-tracks sync depends on."""

    def iter_saved_tracks(self): ...  # AsyncIterator[SavedTrackItem]


@dataclass
class SavedTracksReport:
    """Counts from one saved-tracks pass."""

    added: int = 0
    removed: int = 0
    total_saved: int = 0


async def sync_saved_tracks(
    session: Session, spotify: SavedTracksReader, user: User
) -> SavedTracksReport:
    report = SavedTracksReport()

    remote: dict[str, tuple[SpotifyTrack, datetime | None]] = {}
    async for item in spotify.iter_saved_tracks():
        if item.track.id is None:
            continue  # local files and removed-from-catalog ghosts
        remote[item.track.id] = (item.track, _naive_utc(item.added_at))
    report.total_saved = len(remote)

    stored = session.exec(
        select(SavedTrack, Track)
        .where(SavedTrack.user_id == user.id)
        .where(SavedTrack.track_id == Track.id)
    ).all()
    stored_by_spotify_id = {track.spotify_id: saved for saved, track in stored}

    cache: dict[str, Track] = {}
    for spotify_id, (remote_track, saved_at) in remote.items():
        row = stored_by_spotify_id.get(spotify_id)
        track = upsert_track(session, remote_track, cache)
        if row is None:
            session.add(SavedTrack(user_id=user.id, track_id=track.id, saved_at=saved_at))
            report.added += 1
        elif row.is_removed:
            # Re-saved after a removal: reactivate the same row.
            row.is_removed = False
            row.removed_at = None
            row.saved_at = saved_at
            session.add(row)
            report.added += 1
        elif row.saved_at != saved_at:
            row.saved_at = saved_at
            session.add(row)

    for spotify_id, row in stored_by_spotify_id.items():
        if spotify_id not in remote and not row.is_removed:
            row.is_removed = True
            row.removed_at = utcnow()
            session.add(row)
            report.removed += 1

    session.commit()
    return report
