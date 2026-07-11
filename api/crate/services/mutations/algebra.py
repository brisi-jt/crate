"""Bulk playlist algebra: set expressions → persisted delta previews.

A preview computes exactly what apply will perform (per-playlist adds and
positional removes) and pins the library state with a fingerprint. Apply
replays the stored manifest verbatim; a fingerprint mismatch means the library
moved and the preview must be rebuilt.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import BulkOperation
from crate.model.orm import OpPreview, Playlist, PlaylistTrack, Track, User


def library_fingerprint(session: Session, user_id: int) -> str:
    """sha256 over the user's playlist membership: any add/remove/reorder or
    playlist create/delete produces a different value."""
    playlists = session.exec(
        select(Playlist.id, Playlist.is_deleted)
        .where(Playlist.user_id == user_id)
        .order_by(Playlist.id)
    ).all()
    membership = session.exec(
        select(PlaylistTrack.playlist_id, PlaylistTrack.position, PlaylistTrack.track_id)
        .where(PlaylistTrack.user_id == user_id)
        .order_by(PlaylistTrack.playlist_id, PlaylistTrack.position)
    ).all()
    blob = json.dumps(
        {
            "playlists": [[pid, deleted] for pid, deleted in playlists],
            "membership": [[p, pos, t] for p, pos, t in membership],
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class _Occurrence:
    position: int
    track: Track


def _membership(session: Session, playlist_id: int) -> list[_Occurrence]:
    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(PlaylistTrack.position)
    ).all()
    return [_Occurrence(position=pt.position, track=track) for pt, track in rows]


def _track_ref(track: Track) -> dict[str, Any]:
    artists = track.artists or []
    return {
        "track_id": track.id,
        "spotify_id": track.spotify_id,
        "name": track.name,
        "artist": artists[0]["name"] if artists else "",
    }


def _require_playlist(session: Session, user: User, playlist_id: int) -> Playlist:
    playlist = session.exec(
        select(Playlist)
        .where(Playlist.id == playlist_id)
        .where(Playlist.user_id == user.id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).first()
    if playlist is None:
        raise AppError(
            404,
            "Playlist not found",
            detail=f"No playlist with id {playlist_id}.",
            error_code="PLAYLIST_NOT_FOUND",
        )
    return playlist


def _unique_tracks(occurrences: list[_Occurrence]) -> list[Track]:
    """First occurrence of each track, in playlist order."""
    seen: set[int] = set()
    out: list[Track] = []
    for occ in occurrences:
        if occ.track.id not in seen:
            seen.add(occ.track.id)
            out.append(occ.track)
    return out


def _expression_result(operation: BulkOperation, sources: list[list[_Occurrence]]) -> list[Track]:
    """The expression's result set as an ordered, deduplicated track list."""
    if operation == BulkOperation.union:
        merged: list[Track] = []
        seen: set[int] = set()
        for occurrences in sources:
            for track in _unique_tracks(occurrences):
                if track.id not in seen:
                    seen.add(track.id)
                    merged.append(track)
        return merged
    if operation == BulkOperation.difference:
        exclude = {occ.track.id for occurrences in sources[1:] for occ in occurrences}
        return [t for t in _unique_tracks(sources[0]) if t.id not in exclude]
    if operation == BulkOperation.intersect:
        keep = set.intersection(*({occ.track.id for occ in occurrences} for occurrences in sources))
        return [t for t in _unique_tracks(sources[0]) if t.id in keep]
    raise AssertionError(f"not an expression operation: {operation}")  # pragma: no cover


def _dedupe_removes(occurrences: list[_Occurrence]) -> list[_Occurrence]:
    """Later occurrences duplicating an earlier track id or ISRC."""
    seen_ids: set[int] = set()
    seen_isrcs: set[str] = set()
    removes: list[_Occurrence] = []
    for occ in occurrences:
        duplicate = occ.track.id in seen_ids or (
            occ.track.isrc is not None and occ.track.isrc in seen_isrcs
        )
        if duplicate:
            removes.append(occ)
            continue
        seen_ids.add(occ.track.id)
        if occ.track.isrc is not None:
            seen_isrcs.add(occ.track.isrc)
    return removes


def build_preview(
    session: Session,
    user: User,
    *,
    operation: BulkOperation,
    source_ids: list[int],
    target_id: int | None,
    new_playlist_name: str | None,
) -> OpPreview:
    if not source_ids:
        raise AppError(
            422,
            "Invalid expression",
            detail="At least one source playlist is required.",
            error_code="INVALID_EXPRESSION",
        )
    sources = [_require_playlist(session, user, pid) for pid in source_ids]
    memberships = [_membership(session, p.id) for p in sources]

    entries: list[dict[str, Any]] = []

    if operation in (BulkOperation.union, BulkOperation.difference, BulkOperation.intersect):
        if target_id is None and not new_playlist_name:
            raise AppError(
                422,
                "Invalid expression",
                detail="Set-expression results need a target playlist or a new playlist name.",
                error_code="INVALID_EXPRESSION",
            )
        result = _expression_result(operation, memberships)
        result_ids = {t.id for t in result}
        if target_id is None:
            entries.append(
                {
                    "playlist_id": None,
                    "playlist_name": new_playlist_name,
                    "new": True,
                    "adds": [_track_ref(t) for t in result],
                    "removes": [],
                }
            )
        else:
            target = _require_playlist(session, user, target_id)
            occurrences = _membership(session, target.id)
            kept: set[int] = set()
            removes: list[dict[str, Any]] = []
            for occ in occurrences:
                if occ.track.id in result_ids and occ.track.id not in kept:
                    kept.add(occ.track.id)
                else:
                    removes.append({"position": occ.position, **_track_ref(occ.track)})
            adds = [_track_ref(t) for t in result if t.id not in kept]
            entries.append(
                {
                    "playlist_id": target.id,
                    "playlist_name": target.name,
                    "new": False,
                    "adds": adds,
                    "removes": removes,
                }
            )

    elif operation == BulkOperation.dedupe:
        if len(sources) != 1:
            raise AppError(
                422,
                "Invalid expression",
                detail="Dedupe works on exactly one playlist.",
                error_code="INVALID_EXPRESSION",
            )
        removes = [
            {"position": occ.position, **_track_ref(occ.track)}
            for occ in _dedupe_removes(memberships[0])
        ]
        entries.append(
            {
                "playlist_id": sources[0].id,
                "playlist_name": sources[0].name,
                "new": False,
                "adds": [],
                "removes": removes,
            }
        )

    elif operation == BulkOperation.sync_subset_to_parent:
        if len(sources) != 1 or target_id is None:
            raise AppError(
                422,
                "Invalid expression",
                detail="Subset sync takes one subset playlist and a parent target.",
                error_code="INVALID_EXPRESSION",
            )
        parent = _require_playlist(session, user, target_id)
        parent_ids = {occ.track.id for occ in _membership(session, parent.id)}
        adds = [_track_ref(t) for t in _unique_tracks(memberships[0]) if t.id not in parent_ids]
        entries.append(
            {
                "playlist_id": parent.id,
                "playlist_name": parent.name,
                "new": False,
                "adds": adds,
                "removes": [],
            }
        )

    manifest = {
        "entries": entries,
        "summary": {
            "adds": sum(len(e["adds"]) for e in entries),
            "removes": sum(len(e["removes"]) for e in entries),
            "playlists": len(entries),
        },
    }
    preview = OpPreview(
        user_id=user.id,
        operation=operation,
        params={
            "operation": operation.value,
            "source_ids": source_ids,
            "target_id": target_id,
            "new_playlist_name": new_playlist_name,
        },
        manifest=manifest,
        fingerprint=library_fingerprint(session, user.id),
    )
    session.add(preview)
    session.commit()
    session.refresh(preview)
    return preview
