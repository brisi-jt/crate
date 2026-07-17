"""Ingest parsed history into play_events, parking what can't be resolved.

Resolution fallback chain for each parsed play:

1. **URI match** — the export's ``spotify_track_uri`` yields a spotify id; if a
   catalog ``Track`` already carries that id, the play is ingested straight
   into ``play_events`` (source ``import``).
2. **Parked for re-resolution** — no catalog track has the id yet (the track is
   not in the library). The line is parked in ``history_import_reviews`` as
   ``pending`` with its raw payload; a later import (after the track enters the
   library) resolves it and ingests the play.
3. **Skipped** — lines the parser could not turn into a play at all (podcast
   episodes, local files, zero-listen rows) are parked as ``skipped`` so the
   count is explained without cluttering the pending backlog.

Idempotency has two independent guards:
- ``play_events`` dedupe on ``(user_id, played_at)`` — the export shares its
  per-play timestamps with the recently-played feed, so a re-import (or a
  timestamp that a native capture already holds) never double-inserts.
- ``history_import_reviews`` dedupe on ``(user_id, content_key)`` — re-parking
  the same source line updates the existing review rather than duplicating it.

Inserts are chunked (Vitess dislikes giant multi-row statements).
"""

from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from crate.model.enums import HistoryImportStatus, PlayEventSource
from crate.model.orm import HistoryImportReview, PlayEvent, Track, User
from crate.model.orm.base import utcnow
from crate.services.history.parser import (
    HistoryPlay,
    ParsedHistory,
    SkippedRecord,
    content_key,
)

# Batch size for SELECT ... IN and flush cadence — kept well under Vitess's
# statement limits, matching the insights/imagery batching convention.
_CHUNK = 400


@dataclass
class IngestReport:
    """Counts from one ingestion pass over a parsed export."""

    ingested: int = 0  # new play_events written (fresh URI matches)
    resolved: int = 0  # previously-pending reviews matched + ingested this pass
    parked: int = 0  # new pending review rows (unresolvable-for-now)
    skipped_parked: int = 0  # new skipped review rows (never a play)
    duplicate_plays: int = 0  # plays already present at that (user, played_at)
    duplicate_reviews: int = 0  # review lines already parked
    errors: list[str] = field(default_factory=list)


def _resolve_track_ids(session: Session, spotify_ids: set[str]) -> dict[str, int]:
    """spotify_id -> local Track.id for the ids that exist, chunked."""
    ids = list(spotify_ids)
    resolved: dict[str, int] = {}
    for start in range(0, len(ids), _CHUNK):
        rows = session.exec(
            select(Track.spotify_id, Track.id).where(
                col(Track.spotify_id).in_(ids[start : start + _CHUNK])
            )
        ).all()
        for spotify_id, track_id in rows:
            if track_id is not None:
                resolved[spotify_id] = track_id
    return resolved


def _existing_played_at(session: Session, user_id: int, moments: set) -> set:
    """The subset of played_at values already present for this user, chunked."""
    values = list(moments)
    present: set = set()
    for start in range(0, len(values), _CHUNK):
        rows = session.exec(
            select(PlayEvent.played_at)
            .where(PlayEvent.user_id == user_id)
            .where(col(PlayEvent.played_at).in_(values[start : start + _CHUNK]))
        ).all()
        present.update(rows)
    return present


def _existing_reviews(
    session: Session, user_id: int, keys: set[str]
) -> dict[str, HistoryImportReview]:
    """content_key -> parked review for this user, chunked."""
    values = list(keys)
    found: dict[str, HistoryImportReview] = {}
    for start in range(0, len(values), _CHUNK):
        rows = session.exec(
            select(HistoryImportReview)
            .where(HistoryImportReview.user_id == user_id)
            .where(col(HistoryImportReview.content_key).in_(values[start : start + _CHUNK]))
        ).all()
        for review in rows:
            found[review.content_key] = review
    return found


def ingest_history(session: Session, user: User, parsed: ParsedHistory) -> IngestReport:
    """Ingest a parsed export idempotently. Commits at the end of the pass."""
    report = IngestReport()
    assert user.id is not None

    track_ids = _resolve_track_ids(session, {play.spotify_id for play in parsed.plays})
    existing_moments = _existing_played_at(
        session, user.id, {play.played_at for play in parsed.plays}
    )
    review_keys = {play.content_key for play in parsed.plays}
    review_keys.update(_skip_content_key(s) for s in parsed.skipped)
    existing_reviews = _existing_reviews(session, user.id, review_keys)

    pending = 0
    for play in parsed.plays:
        track_id = track_ids.get(play.spotify_id)
        review = existing_reviews.get(play.content_key)

        if track_id is None:
            # Cannot resolve yet — park (or leave a parked row pending).
            if review is None:
                session.add(_pending_review(user.id, play))
                report.parked += 1
                pending += 1
            else:
                report.duplicate_reviews += 1
            continue

        if play.played_at in existing_moments:
            # Already a play at this instant (re-import or native capture).
            report.duplicate_plays += 1
            if review is not None and review.status != HistoryImportStatus.resolved:
                review.status = HistoryImportStatus.resolved
                review.track_id = track_id
                session.add(review)
                report.resolved += 1
            continue

        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=track_id,
                played_at=play.played_at,
                source=PlayEventSource.import_,
                ms_played=play.ms_played,
            )
        )
        existing_moments.add(play.played_at)
        if review is not None and review.status != HistoryImportStatus.resolved:
            review.status = HistoryImportStatus.resolved
            review.track_id = track_id
            session.add(review)
            report.resolved += 1
        else:
            report.ingested += 1
        pending += 1
        if pending >= _CHUNK:
            session.flush()
            pending = 0

    for skip in parsed.skipped:
        key = _skip_content_key(skip)
        if key in existing_reviews:
            report.duplicate_reviews += 1
            continue
        review = _skipped_review(user.id, key, skip)
        existing_reviews[key] = review
        session.add(review)
        report.skipped_parked += 1

    session.commit()
    return report


def _pending_review(user_id: int, play: HistoryPlay) -> HistoryImportReview:
    return HistoryImportReview(
        user_id=user_id,
        status=HistoryImportStatus.pending,
        content_key=play.content_key,
        played_at=play.played_at,
        raw=play.raw,
    )


def _skip_content_key(skip: SkippedRecord) -> str:
    return content_key(skip.raw.get("ts"), skip.raw.get("spotify_track_uri"))


def _skipped_review(user_id: int, key: str, skip: SkippedRecord) -> HistoryImportReview:
    return HistoryImportReview(
        user_id=user_id,
        status=HistoryImportStatus.skipped,
        content_key=key,
        played_at=utcnow(),
        raw=skip.raw,
    )
