"""Weekly digest generation.

One digest summarizes a Monday-to-Monday week: fresh suggestion counts per
playlist, the best candidates nobody has auditioned yet, library changes the
sync passes observed, listening notes when play history exists, and movement
on the genre frontier. Every item carries deep-link targets (playlist,
candidate, genre) so the inbox can jump straight to the material.

All inputs are local database state — generation never calls Spotify, so the
scheduled pass runs whether or not a credential is connected.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, delete, select

from crate.model.enums import CandidateStatus, DigestSection, SnapshotKind, SyncEventType
from crate.model.orm import (
    Digest,
    DigestItem,
    DiscoveryCandidate,
    PlayEvent,
    Playlist,
    SuggestionFeedback,
    SyncEvent,
    Track,
    User,
    utcnow,
)
from crate.services.analytics.snapshots import get_or_compute
from crate.services.discovery.frontier import compute_frontier_payload
from crate.services.discovery.service import build_suggestion_queue

WEEK = timedelta(days=7)

# Section caps: the digest is a briefing, not a report.
MAX_SUGGESTION_ITEMS = 6
MAX_CANDIDATE_PLAYLISTS = 4
CANDIDATES_PER_PLAYLIST = 2
MAX_LIBRARY_ITEMS = 6
FRONTIER_TOP = 5
MAX_FRONTIER_ITEMS = 3


def week_start_for(moment: datetime) -> datetime:
    """Monday 00:00 of the week containing ``moment`` (all UTC)."""
    monday = moment - timedelta(days=moment.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _owned_playlists(session: Session, user: User) -> dict[int, Playlist]:
    rows = session.exec(
        select(Playlist)
        .where(Playlist.user_id == user.id)
        .where(Playlist.is_owned == True)  # noqa: E712 — SQL expression
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).all()
    return {playlist.id: playlist for playlist in rows if playlist.id is not None}


def _new_candidates_by_playlist(
    session: Session, user: User, playlists: dict[int, Playlist], start: datetime, end: datetime
) -> dict[int, list[DiscoveryCandidate]]:
    rows = session.exec(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.user_id == user.id)
        .where(col(DiscoveryCandidate.created_at) >= start)
        .where(col(DiscoveryCandidate.created_at) < end)
        .order_by(col(DiscoveryCandidate.id))
    ).all()
    grouped: dict[int, list[DiscoveryCandidate]] = {}
    for candidate in rows:
        if candidate.playlist_id in playlists:
            grouped.setdefault(candidate.playlist_id, []).append(candidate)
    return grouped


def _suggestion_items(
    playlists: dict[int, Playlist], grouped: dict[int, list[DiscoveryCandidate]]
) -> list[DigestItem]:
    ranked = sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    items: list[DigestItem] = []
    for playlist_id, candidates in ranked[:MAX_SUGGESTION_ITEMS]:
        count = len(candidates)
        items.append(
            DigestItem(
                digest_id=0,  # set on persist
                position=0,
                section=DigestSection.suggestions,
                title=playlists[playlist_id].name,
                body=f"{count} new suggestion{'s' if count != 1 else ''} queued this week.",
                playlist_id=playlist_id,
                extra={"count": count},
            )
        )
    return items


def _reviewed_candidate_ids(session: Session, user: User) -> set[int]:
    rows = session.exec(
        select(SuggestionFeedback.candidate_id).where(SuggestionFeedback.user_id == user.id)
    ).all()
    return set(rows)


def _candidate_items(
    session: Session,
    user: User,
    playlists: dict[int, Playlist],
    grouped: dict[int, list[DiscoveryCandidate]],
) -> list[DigestItem]:
    """Top-ranked unheard candidates for the week's most active playlists."""
    reviewed = _reviewed_candidate_ids(session, user)
    ranked_playlists = sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    items: list[DigestItem] = []
    for playlist_id, _ in ranked_playlists[:MAX_CANDIDATE_PLAYLISTS]:
        playlist = playlists[playlist_id]
        queue = build_suggestion_queue(session, user, playlist)
        shown = 0
        for entry in queue:
            if shown >= CANDIDATES_PER_PLAYLIST:
                break
            candidate = entry.candidate
            if candidate.id in reviewed or candidate.status != CandidateStatus.resolved:
                continue
            items.append(
                DigestItem(
                    digest_id=0,
                    position=0,
                    section=DigestSection.candidates,
                    title=f"{candidate.title} — {candidate.artist}",
                    body=f"Top of the queue for {playlist.name}.",
                    playlist_id=playlist_id,
                    candidate_id=candidate.id,
                    extra={"fit": round(entry.breakdown.fit, 4)},
                )
            )
            shown += 1
    return items


def _library_items(
    session: Session, user: User, playlists: dict[int, Playlist], start: datetime, end: datetime
) -> list[DigestItem]:
    rows = session.exec(
        select(SyncEvent)
        .where(SyncEvent.user_id == user.id)
        .where(col(SyncEvent.observed_at) >= start)
        .where(col(SyncEvent.observed_at) < end)
    ).all()
    per_playlist: dict[int, dict[str, int]] = {}
    for event in rows:
        if event.playlist_id not in playlists:
            continue
        counts = per_playlist.setdefault(event.playlist_id, {"added": 0, "removed": 0})
        if event.event_type == SyncEventType.added:
            counts["added"] += 1
        elif event.event_type == SyncEventType.removed:
            counts["removed"] += 1

    ranked = sorted(
        per_playlist.items(),
        key=lambda pair: (-(pair[1]["added"] + pair[1]["removed"]), pair[0]),
    )
    items: list[DigestItem] = []
    for playlist_id, counts in ranked[:MAX_LIBRARY_ITEMS]:
        if counts["added"] == 0 and counts["removed"] == 0:
            continue
        parts = []
        if counts["added"]:
            parts.append(f"+{counts['added']}")
        if counts["removed"]:
            parts.append(f"-{counts['removed']}")
        items.append(
            DigestItem(
                digest_id=0,
                position=0,
                section=DigestSection.library,
                title=playlists[playlist_id].name,
                body=f"{' '.join(parts)} tracks over the week.",
                playlist_id=playlist_id,
                extra=counts,
            )
        )
    return items


def _listening_items(
    session: Session, user: User, start: datetime, end: datetime
) -> tuple[list[DigestItem], int]:
    plays = session.exec(
        select(PlayEvent)
        .where(PlayEvent.user_id == user.id)
        .where(col(PlayEvent.played_at) >= start)
        .where(col(PlayEvent.played_at) < end)
    ).all()
    if not plays:
        return [], 0

    track_counts: dict[int, int] = {}
    for play in plays:
        track_counts[play.track_id] = track_counts.get(play.track_id, 0) + 1
    top_track_id = min(track_counts, key=lambda tid: (-track_counts[tid], tid))
    top_track = session.get(Track, top_track_id)

    artist_counts: dict[str, int] = {}
    tracks = {
        track.id: track
        for track in session.exec(select(Track).where(col(Track.id).in_(track_counts))).all()
    }
    for track_id, count in track_counts.items():
        track = tracks.get(track_id)
        if track is None or not track.artists:
            continue
        name = str(track.artists[0].get("name", ""))
        if name:
            artist_counts[name] = artist_counts.get(name, 0) + count
    top_artist = (
        min(artist_counts, key=lambda name: (-artist_counts[name], name)) if artist_counts else None
    )

    body_parts = []
    if top_track is not None:
        body_parts.append(f"Most played: {top_track.name} ({track_counts[top_track_id]} plays)")
    if top_artist is not None:
        body_parts.append(f"top artist {top_artist}")
    item = DigestItem(
        digest_id=0,
        position=0,
        section=DigestSection.listening,
        title=f"{len(plays)} plays this week",
        body=". ".join(body_parts) + "." if body_parts else None,
        extra={
            "plays": len(plays),
            "top_track": top_track.name if top_track else None,
            "top_artist": top_artist,
        },
    )
    return [item], len(plays)


def _frontier_reading(session: Session, user: User) -> list[dict[str, Any]]:
    payload = get_or_compute(
        session,
        user,
        SnapshotKind.frontier,
        lambda: compute_frontier_payload(session, user, owned_only=True),
        owned_only=True,
    )
    return [
        {"name": genre["name"], "score": genre["score"]}
        for genre in payload.get("frontier", [])[:FRONTIER_TOP]
    ]


def _previous_frontier_top(
    session: Session, user: User, week_start: datetime
) -> list[dict[str, Any]] | None:
    previous = session.exec(
        select(Digest)
        .where(Digest.user_id == user.id)
        .where(col(Digest.week_start) < week_start)
        .order_by(col(Digest.week_start).desc())
    ).first()
    if previous is None:
        return None
    return previous.meta.get("frontier_top")


def _frontier_items(
    current_top: list[dict[str, Any]], previous_top: list[dict[str, Any]] | None
) -> list[DigestItem]:
    if previous_top is None:
        movers = current_top[:MAX_FRONTIER_ITEMS]
        note = "New frontier reading."
    else:
        known = {genre["name"] for genre in previous_top}
        movers = [genre for genre in current_top if genre["name"] not in known]
        movers = movers[:MAX_FRONTIER_ITEMS]
        note = "Moved onto the frontier this week."
    return [
        DigestItem(
            digest_id=0,
            position=0,
            section=DigestSection.frontier,
            title=genre["name"],
            body=note,
            genre=genre["name"],
            extra={"score": round(float(genre["score"]), 4)},
        )
        for genre in movers
    ]


def generate_digest(
    session: Session,
    user: User,
    *,
    week_start: datetime | None = None,
    now: datetime | None = None,
) -> Digest:
    """Build (or rebuild) the digest for one week.

    Regenerating an existing week rebuilds its items in place and clears
    read_at — refreshed content counts as unread again.
    """
    assert user.id is not None
    moment = now or utcnow()
    start = week_start or week_start_for(moment)
    end = min(start + WEEK, moment) if moment > start else start + WEEK

    playlists = _owned_playlists(session, user)
    grouped = _new_candidates_by_playlist(session, user, playlists, start, end)

    items: list[DigestItem] = []
    items.extend(_suggestion_items(playlists, grouped))
    items.extend(_candidate_items(session, user, playlists, grouped))
    items.extend(_library_items(session, user, playlists, start, end))
    listening_items, play_count = _listening_items(session, user, start, end)
    items.extend(listening_items)

    frontier_top = _frontier_reading(session, user)
    previous_top = _previous_frontier_top(session, user, start)
    items.extend(_frontier_items(frontier_top, previous_top))

    digest = session.exec(
        select(Digest).where(Digest.user_id == user.id).where(Digest.week_start == start)
    ).first()
    if digest is None:
        digest = Digest(user_id=user.id, week_start=start)
        session.add(digest)
        session.flush()
    else:
        assert digest.id is not None
        session.exec(delete(DigestItem).where(DigestItem.digest_id == digest.id))  # type: ignore[call-overload]
        digest.generated_at = moment
        digest.read_at = None

    digest.meta = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "new_candidates": sum(len(group) for group in grouped.values()),
        "plays": play_count,
        "frontier_top": frontier_top,
    }
    session.add(digest)
    session.flush()
    assert digest.id is not None
    for position, item in enumerate(items):
        item.digest_id = digest.id
        item.position = position
        session.add(item)
    session.commit()
    session.refresh(digest)
    return digest


async def run_weekly_digest_for_user(
    session: Session, user: User, *, now: datetime | None = None
) -> Digest | None:
    """Scheduled entry point: digest the week that just completed.

    Skips quietly when that week's digest already exists — the scheduled pass
    never overwrites what an on-demand regeneration produced.
    """
    moment = now or utcnow()
    completed_week = week_start_for(moment) - WEEK
    existing = session.exec(
        select(Digest).where(Digest.user_id == user.id).where(Digest.week_start == completed_week)
    ).first()
    if existing is not None:
        return None
    return generate_digest(session, user, week_start=completed_week, now=moment)
