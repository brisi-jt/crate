"""Extended-insights engine over a seeded library + play/saved/feedback rows.

Reuses seed_library (6 tracks, 3 owned playlists, t1..t5 enriched) and adds
play_events, saved_tracks, suggestion_feedback, top_items and radio rows so the
cross-table builders have data. Asserts section shapes and a few hand-derivable
values; the pure metrics are proven exhaustively in test_insights_extended_metrics.
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session

from crate.model.enums import PlayEventSource
from crate.model.orm import PlayEvent, User
from crate.services.insights import engine_extended as ex
from tests.test_analytics_endpoints import seed_library

pytestmark = pytest.mark.unit


def _seed_plays(session: Session, user: User, ids: dict[str, int]) -> None:
    base = datetime(2024, 6, 3, 9, 0)  # a Monday morning
    # t1 played 5x (mornings across days), t5 played 1x (night).
    for i in range(5):
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=ids["t1"],
                played_at=base + timedelta(days=i),
                context_type="playlist",
                context_uri="spotify:playlist:sp-Alpha",
                source=PlayEventSource.recent,
            )
        )
    session.add(
        PlayEvent(
            user_id=user.id,
            track_id=ids["t5"],
            played_at=datetime(2024, 6, 3, 22, 0),
            context_type="album",
            context_uri="spotify:album:xyz",
            source=PlayEventSource.recent,
        )
    )
    session.commit()


def test_extended_payload_sections_present(session: Session, user: User) -> None:
    ids = seed_library(session, user)
    _seed_plays(session, user, ids)

    payload = ex.compute_extended_insights_payload(session, user, owned_only=True)

    assert set(payload) == {
        "coverage",
        "play_events",
        "saved",
        "feedback",
        "top_items",
        "radio",
        "journal",
        "cross_table",
    }
    # 6 plays captured (5 t1 + 1 t5).
    assert payload["coverage"]["play_events"] == 6


def test_extended_play_metrics_land(session: Session, user: User) -> None:
    ids = seed_library(session, user)
    _seed_plays(session, user, ids)
    payload = ex.compute_extended_insights_payload(session, user)
    plays = payload["play_events"]
    assert plays["listening_clock"]["total"] == 6
    # context mix: 5 playlist + 1 album.
    ctx = {e["context"]: e["count"] for e in plays["context_mix"]["contexts"]}
    assert ctx["playlist"] == 5
    assert ctx["album"] == 1
    # play/collect gap ranks played tracks (t1 + t5 = 2 distinct).
    assert plays["play_collect_gap"]["played_tracks"] == 2


def test_cross_table_listened_vs_neglected(session: Session, user: User) -> None:
    ids = seed_library(session, user)
    _seed_plays(session, user, ids)
    payload = ex.compute_extended_insights_payload(session, user)
    rows = payload["cross_table"]["listened_vs_neglected"]
    # Alpha received the 5 playlist-context plays.
    by_id = {r["playlist_id"]: r for r in rows}
    assert by_id[ids["Alpha"]]["plays"] == 5


def test_extended_payload_empty_library(session: Session, user: User) -> None:
    # No seed at all: every section renders a pending/empty shape, no crash.
    payload = ex.compute_extended_insights_payload(session, user)
    assert payload["coverage"]["play_events"] == 0
    assert payload["play_events"]["listening_clock"]["total"] == 0
    assert payload["saved"]["total_saved"] == 0
    assert payload["radio"]["keep_rate"]["total"] == 0
