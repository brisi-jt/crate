"""End-to-end import orchestration over a fixture export directory."""

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from crate.model.orm import HistoryImportReview, PlayEvent, Track, User
from crate.services.history.service import import_export

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "history"


def make_track(session: Session, spotify_id: str) -> None:
    session.add(Track(spotify_id=spotify_id, name=f"Track {spotify_id}"))
    session.commit()


def test_imports_a_fixture_export_directory(session: Session, user: User) -> None:
    # The fixture carries two resolvable tracks (2whQ.., 4uLU..), one
    # not-in-library track, one podcast, and one zero-ms play.
    make_track(session, "2whQxHDxButA5STZ32FYme")
    make_track(session, "4uLU6hMCjMI75M1A2tKUQC")

    report = import_export(session, user, FIXTURES)

    assert report.records_read >= 5
    assert report.ingest is not None
    assert report.ingest.ingested == 2
    plays = session.exec(select(PlayEvent).where(PlayEvent.user_id == user.id)).all()
    assert len(plays) == 2
    reviews = session.exec(select(HistoryImportReview)).all()
    assert len(reviews) >= 2  # the unresolved track + the podcast/zero-ms lines


def test_dry_run_writes_nothing(session: Session, user: User) -> None:
    make_track(session, "2whQxHDxButA5STZ32FYme")

    report = import_export(session, user, FIXTURES, dry_run=True)

    assert report.dry_run
    assert report.ingest is None
    assert report.parsed.plays  # parsing still happened
    assert session.exec(select(PlayEvent)).all() == []
    assert session.exec(select(HistoryImportReview)).all() == []


def test_import_export_twice_is_idempotent(session: Session, user: User) -> None:
    make_track(session, "2whQxHDxButA5STZ32FYme")
    make_track(session, "4uLU6hMCjMI75M1A2tKUQC")

    import_export(session, user, FIXTURES)
    plays_first = len(session.exec(select(PlayEvent)).all())
    reviews_first = len(session.exec(select(HistoryImportReview)).all())

    import_export(session, user, FIXTURES)
    assert len(session.exec(select(PlayEvent)).all()) == plays_first
    assert len(session.exec(select(HistoryImportReview)).all()) == reviews_first


def test_fixture_is_the_real_export_shape() -> None:
    # Guards against fixture drift from the documented format.
    data = json.loads((FIXTURES / "Streaming_History_Audio_2021.json").read_text())
    first = data[0]
    for key in (
        "ts",
        "ms_played",
        "spotify_track_uri",
        "master_metadata_track_name",
        "master_metadata_album_artist_name",
        "reason_start",
        "reason_end",
        "skipped",
    ):
        assert key in first
