"""Journal-first playlist mutations.

Every operation follows the same contract:

1. Record the inverse (what restores today's state) in the mutation journal
   and commit — the undo path exists before Spotify hears anything.
2. Perform the Spotify writes (planned by the reconcile planner).
3. Mirror the result locally: membership rows, SyncEvents (source=crate),
   analytics-snapshot invalidation, journal status.

A write failure marks the journal entry `partial`, re-reads the playlist from
Spotify so the local mirror matches reality, and leaves the entry undoable —
undo reconciles from the ACTUAL remote listing back to the recorded inverse,
so recovery works from any half-applied state.
"""

from collections import Counter
from typing import Any

from sqlmodel import Session, col, select

from crate.errors import AppError
from crate.model.enums import (
    MutationOpType,
    MutationStatus,
    SyncEventSource,
    SyncEventType,
)
from crate.model.orm import (
    MutationJournal,
    OpPreview,
    Playlist,
    PlaylistTrack,
    SyncEvent,
    Track,
    User,
    utcnow,
)
from crate.services.analytics.snapshots import invalidate_snapshots
from crate.services.mutations.planner import AddStep, MoveStep, RemoveStep, plan_reconcile
from crate.services.mutations.writer import SpotifyWriter
from crate.services.spotify.client import SpotifyError

TRACK_URI_PREFIX = "spotify:track:"


def track_uri(spotify_id: str) -> str:
    return f"{TRACK_URI_PREFIX}{spotify_id}"


def uri_to_spotify_id(uri: str) -> str:
    return uri.rsplit(":", 1)[-1]


def _not_found(what: str, error_code: str, detail: str) -> AppError:
    return AppError(404, what, detail=detail, error_code=error_code)


class MutationService:
    def __init__(self, *, session: Session, writer: SpotifyWriter, user: User) -> None:
        self._session = session
        self._writer = writer
        self._user = user

    # -- public operations --------------------------------------------------

    async def add_tracks(
        self, playlist_id: int, track_ids: list[int], position: int | None = None
    ) -> MutationJournal:
        playlist = self._require_playlist(playlist_id)
        tracks = self._require_tracks(track_ids)
        old = self._local_uris(playlist)
        if position is not None and not 0 <= position <= len(old):
            raise AppError(
                409,
                "Playlist membership has changed",
                detail=f"Position {position} is outside the current 0..{len(old)} range.",
                error_code="MEMBERSHIP_STALE",
            )
        new_uris = [track_uri(t.spotify_id) for t in tracks]
        target = old + new_uris if position is None else old[:position] + new_uris + old[position:]

        journal = self._journal_first(
            MutationOpType.add_tracks,
            payload={
                "playlist_id": playlist.id,
                "playlist_name": playlist.name,
                "tracks": [
                    {"track_id": t.id, "spotify_id": t.spotify_id, "name": t.name} for t in tracks
                ],
                "position": position,
                "summary": _tracks_summary("Add", tracks, f"→ {playlist.name}"),
            },
            inverse={"kind": "restore_listing", "playlist_id": playlist.id, "order": old},
        )
        await self._apply_membership(journal, playlist, target)
        return journal

    async def remove_tracks(self, playlist_id: int, positions: list[int]) -> MutationJournal:
        playlist = self._require_playlist(playlist_id)
        old = self._local_uris(playlist)
        unique = sorted(set(positions))
        if not unique or unique[0] < 0 or unique[-1] >= len(old):
            raise AppError(
                409,
                "Playlist membership has changed",
                detail="One or more positions are outside the playlist's current range.",
                error_code="MEMBERSHIP_STALE",
            )
        drop = set(unique)
        target = [uri for index, uri in enumerate(old) if index not in drop]
        removed_tracks = self._tracks_by_spotify_ids(
            [uri_to_spotify_id(old[index]) for index in unique]
        )

        journal = self._journal_first(
            MutationOpType.remove_tracks,
            payload={
                "playlist_id": playlist.id,
                "playlist_name": playlist.name,
                "positions": unique,
                "tracks": [
                    {"track_id": t.id, "spotify_id": t.spotify_id, "name": t.name}
                    for t in removed_tracks
                ],
                "summary": _tracks_summary("Remove", removed_tracks, f"from {playlist.name}"),
            },
            inverse={"kind": "restore_listing", "playlist_id": playlist.id, "order": old},
        )
        await self._apply_membership(journal, playlist, target)
        return journal

    async def reorder(self, playlist_id: int, order: list[int]) -> MutationJournal:
        playlist = self._require_playlist(playlist_id)
        rows = self._membership(playlist.id)
        current_ids = [pt.track_id for pt, _ in rows]
        if Counter(order) != Counter(current_ids):
            raise AppError(
                409,
                "Order is stale",
                detail=(
                    "The submitted order is not a permutation of the playlist's "
                    "current tracks — refresh and retry."
                ),
                error_code="ORDER_STALE",
            )
        old = [track_uri(track.spotify_id) for _, track in rows]
        by_id = {track.id: track for _, track in rows}
        target = [track_uri(by_id[track_id].spotify_id) for track_id in order]

        journal = self._journal_first(
            MutationOpType.reorder,
            payload={
                "playlist_id": playlist.id,
                "playlist_name": playlist.name,
                "summary": f"Reorder · {playlist.name}",
            },
            inverse={"kind": "restore_listing", "playlist_id": playlist.id, "order": old},
        )
        await self._apply_membership(journal, playlist, target)
        return journal

    async def create_playlist(self, name: str, description: str | None = None) -> MutationJournal:
        journal = self._journal_first(
            MutationOpType.create_playlist,
            payload={"name": name, "description": description, "summary": f"Create · {name}"},
            inverse={"kind": "unfollow_playlist"},
        )
        try:
            spotify_id, snapshot = await self._writer.create_playlist(name, description)
        except SpotifyError as exc:
            self._fail_journal(journal, exc)

        playlist = Playlist(
            user_id=self._user.id,
            spotify_id=spotify_id,
            name=name,
            description=description,
            snapshot_id=snapshot or None,
            is_owned=True,
            last_synced_at=utcnow(),
        )
        self._session.add(playlist)
        self._session.flush()
        self._emit(playlist, SyncEventType.playlist_created, detail={"track_count": 0})
        journal.payload = {**journal.payload, "playlist_id": playlist.id}
        journal.inverse_payload = {"kind": "unfollow_playlist", "playlist_id": playlist.id}
        self._finish_journal(journal)
        return journal

    async def rename_playlist(
        self,
        playlist_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> MutationJournal:
        playlist = self._require_playlist(playlist_id)
        summary = (
            f"Rename · {playlist.name} → {name}"
            if name and name != playlist.name
            else f"Edit details · {playlist.name}"
        )
        journal = self._journal_first(
            MutationOpType.rename_playlist,
            payload={
                "playlist_id": playlist.id,
                "playlist_name": playlist.name,
                "name": name,
                "description": description,
                "summary": summary,
            },
            inverse={
                "kind": "restore_details",
                "playlist_id": playlist.id,
                "name": playlist.name,
                "description": playlist.description,
            },
        )
        try:
            await self._writer.change_details(
                playlist.spotify_id, name=name, description=description
            )
        except SpotifyError as exc:
            self._fail_journal(journal, exc)

        if name is not None and name != playlist.name:
            self._emit(
                playlist,
                SyncEventType.playlist_renamed,
                detail={"from": playlist.name, "to": name},
            )
            playlist.name = name
        if description is not None:
            playlist.description = description
        self._session.add(playlist)
        self._finish_journal(journal)
        return journal

    async def apply_preview(self, preview: OpPreview) -> MutationJournal:
        from crate.services.mutations.algebra import library_fingerprint

        if library_fingerprint(self._session, self._user.id) != preview.fingerprint:
            raise AppError(
                409,
                "Preview is stale",
                detail=(
                    "The library has changed since this preview was computed — "
                    "run the preview again."
                ),
                error_code="PREVIEW_STALE",
            )

        entries: list[dict[str, Any]] = preview.manifest.get("entries", [])
        summary = preview.manifest.get("summary", {})
        listings = [
            {
                "playlist_id": entry["playlist_id"],
                "order": self._local_uris(self._session.get(Playlist, entry["playlist_id"])),
            }
            for entry in entries
            if not entry.get("new")
        ]
        journal = self._journal_first(
            MutationOpType.bulk,
            payload={
                "operation": preview.operation.value,
                "preview_id": preview.id,
                "summary": _bulk_summary(preview.operation.value, entries, summary),
                "results": [],
            },
            inverse={"kind": "restore_bulk", "listings": listings, "created": []},
        )

        results: list[dict[str, Any]] = []
        created_ids: list[int] = []
        for entry in entries:
            result = await self._apply_bulk_entry(entry, created_ids)
            results.append(result)

        all_ok = all(r["status"] == "applied" for r in results)
        journal.payload = {**journal.payload, "results": results}
        journal.inverse_payload = {
            "kind": "restore_bulk",
            "listings": listings,
            "created": created_ids,
        }
        journal.status = MutationStatus.applied if all_ok else MutationStatus.partial
        self._session.add(journal)
        invalidate_snapshots(self._session, self._user.id)
        self._session.commit()
        self._session.refresh(journal)
        return journal

    async def undo(self, journal_id: int) -> MutationJournal:
        journal = self._session.get(MutationJournal, journal_id)
        if journal is None or journal.user_id != self._user.id:
            raise _not_found(
                "Journal entry not found",
                "JOURNAL_NOT_FOUND",
                f"No journal entry with id {journal_id}.",
            )
        if journal.status not in (MutationStatus.applied, MutationStatus.partial):
            raise AppError(
                409,
                "Not undoable",
                detail=f"Journal entry {journal_id} is {journal.status.value} — "
                "only applied or partial entries can be undone.",
                error_code="NOT_UNDOABLE",
            )

        inverse = journal.inverse_payload
        kind = inverse.get("kind")
        try:
            if kind == "restore_listing":
                await self._restore_listing(inverse["playlist_id"], inverse["order"])
            elif kind == "unfollow_playlist":
                await self._undo_created_playlist(inverse["playlist_id"])
            elif kind == "restore_details":
                await self._restore_details(inverse)
            elif kind == "restore_bulk":
                for listing in inverse.get("listings", []):
                    await self._restore_listing(listing["playlist_id"], listing["order"])
                for playlist_id in inverse.get("created", []):
                    await self._undo_created_playlist(playlist_id)
            else:  # pragma: no cover - defensive
                raise AppError(
                    409,
                    "Not undoable",
                    detail=f"Unknown inverse kind {kind!r}.",
                    error_code="NOT_UNDOABLE",
                )
        except SpotifyError as exc:
            self._session.commit()  # keep any self-heal that happened
            raise AppError(
                502,
                "Spotify write failed",
                detail=f"Undo of journal entry {journal.id} failed mid-way: {exc}. "
                "The entry stays undoable — retry to converge.",
                error_code="SPOTIFY_WRITE_FAILED",
            ) from exc

        journal.status = MutationStatus.undone
        journal.undone_at = utcnow()
        self._session.add(journal)
        invalidate_snapshots(self._session, self._user.id)
        self._session.commit()
        self._session.refresh(journal)
        return journal

    # -- bulk internals ------------------------------------------------------

    async def _apply_bulk_entry(
        self, entry: dict[str, Any], created_ids: list[int]
    ) -> dict[str, Any]:
        name = entry["playlist_name"]
        try:
            if entry.get("new"):
                spotify_id, snapshot = await self._writer.create_playlist(name)
                playlist = Playlist(
                    user_id=self._user.id,
                    spotify_id=spotify_id,
                    name=name,
                    snapshot_id=snapshot or None,
                    is_owned=True,
                    last_synced_at=utcnow(),
                )
                self._session.add(playlist)
                self._session.flush()
                self._emit(playlist, SyncEventType.playlist_created, detail={"track_count": 0})
                created_ids.append(playlist.id)
                old: list[str] = []
            else:
                playlist = self._session.get(Playlist, entry["playlist_id"])
                if playlist is None:  # pragma: no cover - fingerprint guards this
                    return {"playlist_id": entry["playlist_id"], "name": name, "status": "failed"}
                old = self._local_uris(playlist)

            drop = {r["position"] for r in entry.get("removes", [])}
            target = [uri for index, uri in enumerate(old) if index not in drop]
            target += [track_uri(a["spotify_id"]) for a in entry.get("adds", [])]

            plan = plan_reconcile(await self._writer.list_track_uris(playlist.spotify_id), target)
            snapshot_id = await self._execute_plan(playlist, plan)
            self._rewrite_membership(playlist, target)
            if snapshot_id:
                playlist.snapshot_id = snapshot_id
            self._session.add(playlist)
            return {"playlist_id": playlist.id, "name": name, "status": "applied"}
        except SpotifyError as exc:
            if not entry.get("new"):
                playlist = self._session.get(Playlist, entry["playlist_id"])
                if playlist is not None:
                    await self._self_heal(playlist)
            return {
                "playlist_id": entry.get("playlist_id"),
                "name": name,
                "status": "failed",
                "error": str(exc),
            }

    # -- journal plumbing ------------------------------------------------------

    def _journal_first(
        self, op_type: MutationOpType, payload: dict[str, Any], inverse: dict[str, Any]
    ) -> MutationJournal:
        """Persist the journal entry BEFORE any Spotify call."""
        journal = MutationJournal(
            user_id=self._user.id,
            op_type=op_type,
            payload=payload,
            inverse_payload=inverse,
            status=MutationStatus.pending,
        )
        self._session.add(journal)
        self._session.commit()
        self._session.refresh(journal)
        return journal

    def _finish_journal(self, journal: MutationJournal) -> None:
        journal.status = MutationStatus.applied
        self._session.add(journal)
        invalidate_snapshots(self._session, self._user.id)
        self._session.commit()
        self._session.refresh(journal)

    def _fail_journal(self, journal: MutationJournal, exc: SpotifyError) -> None:
        journal.status = MutationStatus.partial
        journal.payload = {**journal.payload, "error": str(exc)}
        self._session.add(journal)
        self._session.commit()
        raise AppError(
            502,
            "Spotify write failed",
            detail=f"The write did not complete: {exc}. Journal entry {journal.id} "
            "records the previous state — undo restores it.",
            error_code="SPOTIFY_WRITE_FAILED",
        ) from exc

    # -- membership application ---------------------------------------------------

    async def _apply_membership(
        self, journal: MutationJournal, playlist: Playlist, target: list[str]
    ) -> None:
        old = self._local_uris(playlist)
        plan = plan_reconcile(old, target)
        try:
            snapshot_id = await self._execute_plan(playlist, plan)
        except SpotifyError as exc:
            await self._self_heal(playlist)
            self._fail_journal(journal, exc)
            return  # pragma: no cover - _fail_journal always raises

        self._rewrite_membership(playlist, target)
        if snapshot_id:
            playlist.snapshot_id = snapshot_id
        self._session.add(playlist)
        self._finish_journal(journal)

    async def _execute_plan(self, playlist: Playlist, plan: list[Any]) -> str | None:
        snapshot: str | None = None
        for step in plan:
            if isinstance(step, RemoveStep):
                snapshot = await self._writer.remove_tracks(playlist.spotify_id, list(step.uris))
            elif isinstance(step, AddStep):
                snapshot = await self._writer.add_tracks(
                    playlist.spotify_id, list(step.uris), step.position
                )
            elif isinstance(step, MoveStep):
                snapshot = await self._writer.reorder_range(
                    playlist.spotify_id, step.range_start, step.insert_before
                )
        return snapshot

    async def _restore_listing(self, playlist_id: int, order: list[str]) -> None:
        playlist = self._session.get(Playlist, playlist_id)
        if playlist is None:  # pragma: no cover - journals reference real rows
            return
        remote = await self._writer.list_track_uris(playlist.spotify_id)
        plan = plan_reconcile(remote, order)
        snapshot_id = await self._execute_plan(playlist, plan)
        self._rewrite_membership(playlist, order)
        if snapshot_id:
            playlist.snapshot_id = snapshot_id
        self._session.add(playlist)

    async def _undo_created_playlist(self, playlist_id: int) -> None:
        playlist = self._session.get(Playlist, playlist_id)
        if playlist is None:  # pragma: no cover - journals reference real rows
            return
        await self._writer.unfollow_playlist(playlist.spotify_id)
        playlist.is_deleted = True
        self._session.add(playlist)
        self._emit(playlist, SyncEventType.playlist_deleted)

    async def _restore_details(self, inverse: dict[str, Any]) -> None:
        playlist = self._session.get(Playlist, inverse["playlist_id"])
        if playlist is None:  # pragma: no cover - journals reference real rows
            return
        await self._writer.change_details(
            playlist.spotify_id, name=inverse["name"], description=inverse["description"]
        )
        if playlist.name != inverse["name"]:
            self._emit(
                playlist,
                SyncEventType.playlist_renamed,
                detail={"from": playlist.name, "to": inverse["name"]},
            )
        playlist.name = inverse["name"]
        playlist.description = inverse["description"]
        self._session.add(playlist)

    async def _self_heal(self, playlist: Playlist) -> None:
        """After a failed write, mirror whatever state Spotify actually holds."""
        try:
            remote = await self._writer.list_track_uris(playlist.spotify_id)
        except SpotifyError:
            return  # next sync reconciles; local stays at the last known state
        known = {
            uri
            for uri in remote
            if self._session.exec(
                select(Track).where(Track.spotify_id == uri_to_spotify_id(uri))
            ).first()
        }
        self._rewrite_membership(playlist, [uri for uri in remote if uri in known])
        self._session.add(playlist)

    # -- local state ---------------------------------------------------------------

    def _rewrite_membership(self, playlist: Playlist, target: list[str]) -> None:
        """Replace membership rows with `target`, preserving added_at where the
        same track stays, and emit crate-sourced SyncEvents for the diff."""
        rows = self._membership(playlist.id)
        old_sids = [track.spotify_id for _, track in rows]
        new_sids = [uri_to_spotify_id(uri) for uri in target]

        # added_at values to carry over, per spotify id, in position order.
        carried: dict[str, list[Any]] = {}
        for pt, track in rows:
            carried.setdefault(track.spotify_id, []).append(pt.added_at)

        tracks = {
            t.spotify_id: t for t in self._tracks_by_spotify_ids(new_sids, allow_missing=True)
        }

        self._emit_membership_events(playlist, old_sids, new_sids)

        for pt, _ in rows:
            self._session.delete(pt)
        self._session.flush()  # release the (playlist_id, position) unique constraint
        for position, sid in enumerate(new_sids):
            queue = carried.get(sid)
            added_at = queue.pop(0) if queue else utcnow()
            self._session.add(
                PlaylistTrack(
                    user_id=self._user.id,
                    playlist_id=playlist.id,
                    track_id=tracks[sid].id,
                    position=position,
                    added_at=added_at,
                )
            )

    def _emit_membership_events(
        self, playlist: Playlist, old_sids: list[str], new_sids: list[str]
    ) -> None:
        old_counts = Counter(old_sids)
        new_counts = Counter(new_sids)
        track_ids = {
            t.spotify_id: t.id
            for t in self._tracks_by_spotify_ids(
                list(set(old_sids) | set(new_sids)), allow_missing=True
            )
        }
        for sid, count in new_counts.items():
            for _ in range(count - old_counts.get(sid, 0)):
                self._emit(playlist, SyncEventType.added, track_id=track_ids.get(sid))
        for sid, count in old_counts.items():
            for _ in range(count - new_counts.get(sid, 0)):
                self._emit(playlist, SyncEventType.removed, track_id=track_ids.get(sid))
        if old_counts == new_counts and old_sids != new_sids:
            self._emit(playlist, SyncEventType.reordered)

    def _emit(
        self,
        playlist: Playlist,
        event_type: SyncEventType,
        *,
        track_id: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            SyncEvent(
                user_id=self._user.id,
                playlist_id=playlist.id,
                track_id=track_id,
                event_type=event_type,
                source=SyncEventSource.crate,
                observed_at=utcnow(),
                detail=detail,
            )
        )

    # -- lookups -------------------------------------------------------------------

    def _require_playlist(self, playlist_id: int) -> Playlist:
        playlist = self._session.exec(
            select(Playlist)
            .where(Playlist.id == playlist_id)
            .where(Playlist.user_id == self._user.id)
            .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
        ).first()
        if playlist is None:
            raise _not_found(
                "Playlist not found",
                "PLAYLIST_NOT_FOUND",
                f"No playlist with id {playlist_id}.",
            )
        return playlist

    def _require_tracks(self, track_ids: list[int]) -> list[Track]:
        tracks = []
        for track_id in track_ids:
            track = self._session.get(Track, track_id)
            if track is None:
                raise _not_found(
                    "Track not found", "TRACK_NOT_FOUND", f"No track with id {track_id}."
                )
            tracks.append(track)
        return tracks

    def _tracks_by_spotify_ids(
        self, spotify_ids: list[str], allow_missing: bool = False
    ) -> list[Track]:
        unique = list(dict.fromkeys(spotify_ids))
        found = self._session.exec(select(Track).where(col(Track.spotify_id).in_(unique))).all()
        rows = {t.spotify_id: t for t in found}
        if not allow_missing:
            return [rows[sid] for sid in spotify_ids]
        return [rows[sid] for sid in unique if sid in rows]

    def _membership(self, playlist_id: int) -> list[tuple[PlaylistTrack, Track]]:
        return list(
            self._session.exec(
                select(PlaylistTrack, Track)
                .where(PlaylistTrack.playlist_id == playlist_id)
                .where(PlaylistTrack.track_id == Track.id)
                .order_by(PlaylistTrack.position)
            ).all()
        )

    def _local_uris(self, playlist: Playlist) -> list[str]:
        return [track_uri(track.spotify_id) for _, track in self._membership(playlist.id)]


# -- summaries ------------------------------------------------------------------


def _tracks_summary(verb: str, tracks: list[Track], suffix: str) -> str:
    if not tracks:
        return f"{verb} · {suffix}"
    first = tracks[0].name
    more = f" +{len(tracks) - 1} more" if len(tracks) > 1 else ""
    return f"{verb} · {first}{more} {suffix}"


def _bulk_summary(operation: str, entries: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    target = entries[0]["playlist_name"] if entries else "—"
    adds = summary.get("adds", 0)
    removes = summary.get("removes", 0)
    return f"Bulk · {operation} → {target} · +{adds} -{removes}"
