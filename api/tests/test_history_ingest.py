"""History ingestion — resolution fallback, dedupe idempotency, provenance."""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from crate.model.enums import HistoryImportStatus, PlayEventSource
from crate.model.orm import HistoryImportReview, PlayEvent, Track, User
from crate.services.history.ingest import ingest_history
from crate.services.history.parser import parse_history_records

pytestmark = pytest.mark.unit


def rec(spotify_id: str | None, ts: str, ms_played: int = 200_000, **overrides):
    uri = f"spotify:track:{spotify_id}" if spotify_id else None
    record: dict[str, object] = {
        "ts": ts,
        "ms_played": ms_played,
        "spotify_track_uri": uri,
        "master_metadata_track_name": f"Track {spotify_id}",
        "master_metadata_album_artist_name": f"Artist {spotify_id}",
        "master_metadata_album_album_name": None,
    }
    record.update(overrides)
    return record


def make_track(session: Session, spotify_id: str) -> Track:
    track = Track(spotify_id=spotify_id, name=f"Track {spotify_id}")
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def _ingest(session: Session, user: User, records: list[dict]):
    parsed = parse_history_records(records)
    return ingest_history(session, user, parsed)


def test_uri_match_ingests_a_play_event(session: Session, user: User) -> None:
    make_track(session, "abc")

    report = _ingest(session, user, [rec("abc", "2021-06-30T22:34:47Z")])

    assert report.ingested == 1
    plays = session.exec(select(PlayEvent).where(PlayEvent.user_id == user.id)).all()
    assert len(plays) == 1
    assert plays[0].played_at == datetime(2021, 6, 30, 22, 34, 47)
    assert plays[0].ms_played == 200_000
    assert plays[0].source == PlayEventSource.import_


def test_unresolvable_track_is_parked_in_review(session: Session, user: User) -> None:
    # No local Track with this spotify_id → cannot resolve → review row.
    report = _ingest(session, user, [rec("missing", "2021-06-30T22:34:47Z")])

    assert report.ingested == 0
    assert report.parked == 1
    reviews = session.exec(select(HistoryImportReview)).all()
    assert len(reviews) == 1
    assert reviews[0].status == HistoryImportStatus.pending
    assert reviews[0].track_id is None
    assert reviews[0].raw["spotify_track_uri"] == "spotify:track:missing"


def test_skipped_records_are_parked_as_skipped(session: Session, user: User) -> None:
    # A podcast (no track uri) → parsed skip → review row with skipped status.
    report = _ingest(session, user, [rec(None, "2021-06-30T22:34:47Z")])

    assert report.ingested == 0
    reviews = session.exec(select(HistoryImportReview)).all()
    assert len(reviews) == 1
    assert reviews[0].status == HistoryImportStatus.skipped


def test_import_twice_is_idempotent_zero_new_rows(session: Session, user: User) -> None:
    make_track(session, "abc")
    records = [
        rec("abc", "2021-06-30T22:34:47Z"),
        rec("missing", "2021-06-30T23:00:00Z"),
        rec(None, "2021-07-01T00:00:00Z"),
    ]

    first = _ingest(session, user, records)
    plays_after_first = session.exec(select(PlayEvent)).all()
    reviews_after_first = session.exec(select(HistoryImportReview)).all()

    second = _ingest(session, user, records)
    plays_after_second = session.exec(select(PlayEvent)).all()
    reviews_after_second = session.exec(select(HistoryImportReview)).all()

    # Import twice = zero new rows (the F2 idempotency requirement).
    assert len(plays_after_second) == len(plays_after_first)
    assert len(reviews_after_second) == len(reviews_after_first)
    assert second.ingested == 0
    assert second.parked == 0
    assert second.skipped_parked == 0
    # Every line the first pass wrote is now recognised as a duplicate.
    assert second.duplicate_plays == first.ingested
    assert second.duplicate_reviews == first.parked + first.skipped_parked


def test_import_does_not_collide_with_recently_played_at_same_ts(
    session: Session, user: User
) -> None:
    # A native capture already exists at this played_at; the import must not
    # error on the (user_id, played_at) unique constraint — it skips as a dup.
    track = make_track(session, "abc")
    session.add(
        PlayEvent(
            user_id=user.id,
            track_id=track.id,
            played_at=datetime(2021, 6, 30, 22, 34, 47),
            source=PlayEventSource.recent,
        )
    )
    session.commit()

    report = _ingest(session, user, [rec("abc", "2021-06-30T22:34:47Z")])

    assert report.ingested == 0
    assert report.duplicate_plays == 1
    plays = session.exec(select(PlayEvent)).all()
    assert len(plays) == 1
    assert plays[0].source == PlayEventSource.recent  # the native row is untouched


def test_reresolution_flips_pending_review_to_resolved_and_ingests(
    session: Session, user: User
) -> None:
    # First import parks the track (not yet in library); after it enters the
    # library, a re-import resolves the parked row and ingests the play.
    records = [rec("abc", "2021-06-30T22:34:47Z")]
    _ingest(session, user, records)
    assert session.exec(select(PlayEvent)).all() == []

    make_track(session, "abc")
    report = _ingest(session, user, records)

    assert report.resolved == 1
    plays = session.exec(select(PlayEvent)).all()
    assert len(plays) == 1
    review = session.exec(select(HistoryImportReview)).one()
    assert review.status == HistoryImportStatus.resolved
    assert review.track_id is not None
