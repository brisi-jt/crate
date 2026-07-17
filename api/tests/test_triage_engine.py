"""Suggestion engine: score one track against ALL owned playlists.

Each destination suggestion carries four separately-labeled evidence rows
(sonic_fit, artist_overlap, placement_history, vibe_match) — never a blended
score. Each signal is provable in isolation on a fixture library.
"""

import pytest
from sqlmodel import Session

from crate.model.enums import EvidenceKind, FeatureStatus
from crate.model.orm import (
    ArtistGenre,
    Genre,
    Playlist,
    PlaylistTrack,
    Track,
    TrackFeatures,
    User,
)
from crate.services.triage.engine import suggest_destinations

pytestmark = pytest.mark.unit


def _track(session: Session, sid: str, artist: str, features: dict | None = None) -> int:
    row = Track(
        spotify_id=sid, name=f"Track {sid}", artists=[{"spotify_id": f"a-{sid}", "name": artist}]
    )
    session.add(row)
    session.flush()
    assert row.id is not None
    if features is not None:
        session.add(TrackFeatures(track_id=row.id, status=FeatureStatus.present, **features))
    return row.id


def _playlist(session: Session, user: User, name: str, description: str | None = None) -> int:
    row = Playlist(
        user_id=user.id, spotify_id=f"sp-{name}", name=name, description=description, is_owned=True
    )
    session.add(row)
    session.flush()
    assert row.id is not None
    return row.id


def _add(session: Session, user: User, pl: int, tid: int, pos: int = 0) -> None:
    session.add(PlaylistTrack(user_id=user.id, playlist_id=pl, track_id=tid, position=pos))


# Fixture features: high-energy vs low-energy poles so proximity is decisive.
HI = {"energy": 0.9, "valence": 0.8, "acousticness": 0.1, "danceability": 0.8}
LO = {"energy": 0.1, "valence": 0.2, "acousticness": 0.9, "danceability": 0.2}


def _seed_calibration_library(session: Session, user: User) -> dict[str, int]:
    """A library with a clearly hi-energy playlist and a clearly lo-energy one."""
    ids: dict[str, int] = {}
    gym = _playlist(session, user, "Gym")
    chill = _playlist(session, user, "Chill")
    ids["Gym"] = gym
    ids["Chill"] = chill
    for i in range(6):
        t = _track(session, f"hi{i}", f"HiArtist{i}", HI)
        _add(session, user, gym, t, i)
    for i in range(6):
        t = _track(session, f"lo{i}", f"LoArtist{i}", LO)
        _add(session, user, chill, t, i)
    session.commit()
    return ids


def _evidence_by_kind(suggestion) -> dict[EvidenceKind, object]:
    return {e.kind: e for e in suggestion.evidence}


# -- sonic fit -----------------------------------------------------------------


def test_sonic_fit_ranks_matching_playlist_first(session: Session, user: User) -> None:
    ids = _seed_calibration_library(session, user)
    # A hi-energy candidate should fit Gym better than Chill.
    filed = _track(session, "cand", "NewArtist", HI)
    session.commit()

    suggestions = suggest_destinations(session, user, filed)
    order = [s.playlist_id for s in suggestions]
    assert order.index(ids["Gym"]) < order.index(ids["Chill"])

    top = suggestions[order.index(ids["Gym"])]
    ev = _evidence_by_kind(top)
    assert EvidenceKind.sonic_fit in ev
    # Every suggestion carries all four evidence rows, separately labeled.
    assert {e.kind for e in top.evidence} == set(EvidenceKind)


# -- artist overlap ------------------------------------------------------------


def test_artist_overlap_counts_same_artist(session: Session, user: User) -> None:
    gym = _playlist(session, user, "Gym")
    # Three tracks by "Repeat Artist" already in Gym.
    for i in range(3):
        t = _track(session, f"g{i}", "Repeat Artist", HI)
        _add(session, user, gym, t, i)
    filed = _track(session, "cand", "Repeat Artist", HI)
    session.commit()

    suggestions = suggest_destinations(session, user, filed)
    gym_sug = next(s for s in suggestions if s.playlist_id == gym)
    overlap = _evidence_by_kind(gym_sug)[EvidenceKind.artist_overlap]
    assert overlap.detail["count"] == 3
    assert "Repeat Artist" in overlap.summary


# -- vibe match ----------------------------------------------------------------


def test_vibe_match_uses_name_and_genres(session: Session, user: User) -> None:
    jazz = _playlist(session, user, "Late Night Jazz", description="smooth after-hours")
    for i in range(3):
        _add(session, user, jazz, _track(session, f"j{i}", f"JazzArtist{i}", LO), i)
    # The candidate's artist is tagged with the "jazz" genre.
    filed = _track(session, "cand", "Coltrane", LO)
    genre = Genre(name="jazz", enao_rank=100)
    session.add(genre)
    session.flush()
    session.add(ArtistGenre(genre_id=genre.id, artist_name="coltrane", weight=1.0))
    session.commit()

    suggestions = suggest_destinations(session, user, filed)
    jazz_sug = next(s for s in suggestions if s.playlist_id == jazz)
    vibe = _evidence_by_kind(jazz_sug)[EvidenceKind.vibe_match]
    assert "jazz" in vibe.detail.get("matched", [])


# -- already-in flag -----------------------------------------------------------


def test_already_in_playlist_flagged_but_still_suggested(session: Session, user: User) -> None:
    gym = _playlist(session, user, "Gym")
    filed = _track(session, "cand", "A", HI)
    _add(session, user, gym, filed, 0)
    # A second live playlist so there is something to rank.
    _playlist(session, user, "Other")
    session.commit()

    suggestions = suggest_destinations(session, user, filed)
    gym_sug = next(s for s in suggestions if s.playlist_id == gym)
    assert gym_sug.already_in is True


def test_engine_handles_track_without_features(session: Session, user: User) -> None:
    _seed_calibration_library(session, user)
    filed = _track(session, "cand", "NewArtist", None)  # no features
    session.commit()
    # Must not crash; sonic_fit falls back to neutral.
    suggestions = suggest_destinations(session, user, filed)
    assert suggestions  # still ranks playlists
    for s in suggestions:
        assert {e.kind for e in s.evidence} == set(EvidenceKind)
