"""Membership reverse-lookup helper: track -> live owned playlists.

Serves panel 2 (current memberships) and the ≤N Liked-mode filter. Must exclude
soft-deleted playlists (assertion, not assumption).
"""

import pytest
from sqlmodel import Session

from crate.model.orm import Playlist, PlaylistTrack, Track, User
from crate.services.triage.membership import (
    find_playlists_for_tracks,
    playlist_exclusions,
)

pytestmark = pytest.mark.unit


def _seed(session: Session, user: User) -> dict[str, int]:
    ids: dict[str, int] = {}
    for sid in ["t1", "t2", "t3"]:
        track = Track(spotify_id=sid, name=f"Track {sid}", artists=[])
        session.add(track)
        session.flush()
        ids[sid] = track.id
    # Gym holds t1, t2; Pool holds t1; Dead (soft-deleted) holds t1.
    for name, members, deleted in [
        ("Gym", ["t1", "t2"], False),
        ("Pool", ["t1"], False),
        ("Dead", ["t1"], True),
    ]:
        pl = Playlist(
            user_id=user.id, spotify_id=f"sp-{name}", name=name, is_owned=True, is_deleted=deleted
        )
        session.add(pl)
        session.flush()
        ids[name] = pl.id
        for pos, sid in enumerate(members):
            session.add(
                PlaylistTrack(user_id=user.id, playlist_id=pl.id, track_id=ids[sid], position=pos)
            )
    session.commit()
    return ids


def test_find_playlists_maps_tracks_to_live_owned_playlists(session: Session, user: User) -> None:
    ids = _seed(session, user)
    result = find_playlists_for_tracks(session, user.id, [ids["t1"], ids["t2"], ids["t3"]])

    # t1 is in Gym + Pool (Dead excluded — soft-deleted).
    assert sorted(result[ids["t1"]]) == sorted([ids["Gym"], ids["Pool"]])
    assert result[ids["t2"]] == [ids["Gym"]]
    # t3 is in nothing.
    assert result.get(ids["t3"], []) == []


def test_find_playlists_excludes_soft_deleted(session: Session, user: User) -> None:
    ids = _seed(session, user)
    result = find_playlists_for_tracks(session, user.id, [ids["t1"]])
    assert ids["Dead"] not in result[ids["t1"]]


def test_find_playlists_empty_input(session: Session, user: User) -> None:
    _seed(session, user)
    assert find_playlists_for_tracks(session, user.id, []) == {}


def test_membership_still_includes_excluded_playlists(session: Session, user: User) -> None:
    """An excluded playlist is still a live membership — a fact the panel shows."""
    ids = _seed(session, user)
    gym = session.get(Playlist, ids["Gym"])
    assert gym is not None
    gym.triage_excluded = True
    session.add(gym)
    session.commit()

    result = find_playlists_for_tracks(session, user.id, [ids["t1"]])
    # Excluded from suggestions/queue, but still reported as a current membership.
    assert ids["Gym"] in result[ids["t1"]]


def test_playlist_exclusions_flags_excluded(session: Session, user: User) -> None:
    ids = _seed(session, user)
    gym = session.get(Playlist, ids["Gym"])
    assert gym is not None
    gym.triage_excluded = True
    session.add(gym)
    session.commit()

    flags = playlist_exclusions(session, user.id)
    assert flags[ids["Gym"]] is True
    assert flags[ids["Pool"]] is False
    # Soft-deleted playlists are not live -> absent from the map.
    assert ids["Dead"] not in flags
