"""Insights engine payload over the shared analytics micro-fixture.

Reuses seed_library from the analytics endpoint tests (6 tracks, 3 playlists,
t1..t5 enriched with per-index features, key=0/mode=1 → 8B, added_at spanning
2025). Asserts the payload's section shapes and a few hand-derivable values.
"""

import pytest
from sqlmodel import Session, col, select

from crate.model.orm import Track, User
from crate.services.insights import engine
from tests.test_analytics_endpoints import seed_library

pytestmark = pytest.mark.unit


def test_insights_payload_sections_present(session: Session, user: User) -> None:
    seed_library(session, user)
    payload = engine.compute_insights_payload(session, user, owned_only=True)

    assert set(payload) == {
        "coverage",
        "taste_identity",
        "sonic_signatures",
        "archaeology",
        "eras",
        "extremes",
    }
    # 6 tracks in owned scope, 5 enriched.
    assert payload["coverage"]["total_tracks"] == 6
    assert payload["coverage"]["enriched_tracks"] == 5


def test_fingerprint_has_nine_features(session: Session, user: User) -> None:
    seed_library(session, user)
    payload = engine.compute_insights_payload(session, user)
    fp = payload["taste_identity"]["fingerprint"]
    assert len(fp) == 9
    # every enriched track has identical percentiles across features, so the
    # library mean is identical across features too.
    values = {round(entry["percentile"], 4) for entry in fp}
    assert len(values) == 1


def test_camelot_all_8b(session: Session, user: User) -> None:
    seed_library(session, user)
    payload = engine.compute_insights_payload(session, user)
    camelot = payload["sonic_signatures"]["camelot"]
    # key=0, mode=1 = C major = 8B for all 5 enriched tracks.
    assert len(camelot) == 1
    assert camelot[0]["code"] == "8B"
    assert camelot[0]["count"] == 5


def test_extremes_names_real_tracks(session: Session, user: User) -> None:
    seed_library(session, user)
    payload = engine.compute_insights_payload(session, user)
    board = payload["extremes"]
    names = {entry["name"] for entry in board}
    assert names  # non-empty
    assert all(name.startswith("Track ") for name in names)


def test_era_profile_reads_release_years(session: Session, user: User) -> None:
    seed_library(session, user)
    # date two tracks: 1999 and 2011.
    tracks = session.exec(select(Track).where(col(Track.spotify_id).in_(["sp-t1", "sp-t2"]))).all()
    for track, year in zip(tracks, (1999, 2011), strict=False):
        track.release_year = year
        track.release_date = str(year)
        session.add(track)
    session.commit()

    payload = engine.compute_insights_payload(session, user)
    era = payload["eras"]
    assert era["total"] == 2
    decades = {d["decade"] for d in era["decades"]}
    assert decades == {1990, 2010}


def test_coming_of_age_only_with_birth_year(session: Session, user: User) -> None:
    seed_library(session, user)
    track = session.exec(select(Track).where(Track.spotify_id == "sp-t1")).first()
    assert track is not None
    track.release_year = 2011
    session.add(track)
    user.birth_year = 1992  # band 2008..2016 -> 2011 in band
    session.add(user)
    session.commit()

    payload = engine.compute_insights_payload(session, user)
    assert payload["coverage"]["birth_year_set"] is True
    assert payload["eras"]["coming_of_age"]["count"] == 1
