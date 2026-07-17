"""Track -> live owned-playlist membership reverse lookup.

`PlaylistTrack` is indexed on user_id/playlist_id/track_id, but the only
existing inversion is in-memory in the analytics engine. Triage needs a batch
reverse lookup for two things: panel 2's current-memberships list and the
Liked-mode ≤N filter's live membership count. Both must exclude soft-deleted
playlists, so the join carries `Playlist.is_deleted == False`.
"""

from sqlmodel import Session, col, select

from crate.model.orm import Playlist, PlaylistTrack


def find_playlists_for_tracks(
    session: Session, user_id: int, track_ids: list[int]
) -> dict[int, list[int]]:
    """track id -> live owned-playlist ids holding it (soft-deleted excluded).

    One query joined to Playlist for liveness. Tracks in no live playlist are
    absent from the result (callers default to []).
    """
    if not track_ids:
        return {}
    rows = session.exec(
        select(PlaylistTrack.track_id, PlaylistTrack.playlist_id)
        .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)  # type: ignore[arg-type]
        .where(PlaylistTrack.user_id == user_id)
        .where(col(PlaylistTrack.track_id).in_(track_ids))
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).all()
    result: dict[int, list[int]] = {}
    for track_id, playlist_id in rows:
        bucket = result.setdefault(track_id, [])
        if playlist_id not in bucket:  # a track can repeat within a playlist
            bucket.append(playlist_id)
    return result


def playlist_names(session: Session, user_id: int) -> dict[int, str]:
    """Live owned-playlist id -> name, for rendering the membership badges."""
    rows = session.exec(
        select(Playlist.id, Playlist.name)
        .where(Playlist.user_id == user_id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).all()
    return {pid: name for pid, name in rows if pid is not None}
