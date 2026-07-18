"""Triage queue assembly.

Playlist mode: the source playlist's tracks, added_at ascending (oldest-waiting
first — a true inbox). Liked mode: saved (not-removed) tracks filtered to those
in <= N live owned playlists, with the filter pushed into SQL so `total` and
page boundaries are correct at every N (P0-4).
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session

from crate.model.orm import Playlist, PlaylistTrack, SavedTrack, Track, User
from crate.services.triage.queue import QueueSource, load_queue

pytestmark = pytest.mark.unit

BASE = datetime(2026, 1, 1)


def _track(session: Session, sid: str) -> int:
    row = Track(spotify_id=sid, name=f"Track {sid}", artists=[])
    session.add(row)
    session.flush()
    assert row.id is not None
    return row.id


def _playlist(session: Session, user: User, name: str, deleted: bool = False) -> int:
    row = Playlist(
        user_id=user.id, spotify_id=f"sp-{name}", name=name, is_owned=True, is_deleted=deleted
    )
    session.add(row)
    session.flush()
    assert row.id is not None
    return row.id


def _add(session: Session, user: User, pl: int, tid: int, pos: int, added: datetime) -> None:
    session.add(
        PlaylistTrack(user_id=user.id, playlist_id=pl, track_id=tid, position=pos, added_at=added)
    )


def _save(session: Session, user: User, tid: int, removed: bool = False) -> None:
    session.add(SavedTrack(user_id=user.id, track_id=tid, saved_at=BASE, is_removed=removed))


# -- playlist mode -------------------------------------------------------------


def test_playlist_mode_orders_by_added_at_ascending(session: Session, user: User) -> None:
    pl = _playlist(session, user, "Triage")
    a = _track(session, "a")
    b = _track(session, "b")
    c = _track(session, "c")
    # Insert out of added_at order.
    _add(session, user, pl, b, 0, BASE + timedelta(days=2))
    _add(session, user, pl, a, 1, BASE + timedelta(days=1))
    _add(session, user, pl, c, 2, BASE + timedelta(days=3))
    session.commit()

    result = load_queue(session, user.id, QueueSource(playlist_id=pl), limit=10, offset=0)
    assert [e.track_id for e in result.items] == [a, b, c]  # oldest-waiting first
    assert result.total == 3


def test_playlist_mode_pagination(session: Session, user: User) -> None:
    pl = _playlist(session, user, "Triage")
    tids = [_track(session, f"t{i}") for i in range(5)]
    for i, tid in enumerate(tids):
        _add(session, user, pl, tid, i, BASE + timedelta(days=i))
    session.commit()

    page = load_queue(session, user.id, QueueSource(playlist_id=pl), limit=2, offset=2)
    assert page.total == 5
    assert [e.track_id for e in page.items] == [tids[2], tids[3]]


# -- liked mode: the ≤N filter (P0-4) ------------------------------------------


def test_liked_mode_orphans_only_n_zero(session: Session, user: User) -> None:
    """N=0: only saved tracks in ZERO live playlists (orphans)."""
    gym = _playlist(session, user, "Gym")
    orphan = _track(session, "orphan")
    filed = _track(session, "filed")
    _save(session, user, orphan)
    _save(session, user, filed)
    _add(session, user, gym, filed, 0, BASE)
    session.commit()

    result = load_queue(
        session, user.id, QueueSource(liked=True, max_playlists=0), limit=10, offset=0
    )
    assert [e.track_id for e in result.items] == [orphan]
    assert result.total == 1  # total is over the FILTERED set


def test_liked_mode_n_one_includes_singly_filed(session: Session, user: User) -> None:
    gym = _playlist(session, user, "Gym")
    pool = _playlist(session, user, "Pool")
    orphan = _track(session, "orphan")
    once = _track(session, "once")
    twice = _track(session, "twice")
    for t in (orphan, once, twice):
        _save(session, user, t)
    _add(session, user, gym, once, 0, BASE)
    _add(session, user, gym, twice, 1, BASE)
    _add(session, user, pool, twice, 0, BASE)
    session.commit()

    result = load_queue(
        session, user.id, QueueSource(liked=True, max_playlists=1), limit=10, offset=0
    )
    # orphan (0) and once (1) qualify; twice (2) does not.
    assert sorted(e.track_id for e in result.items) == sorted([orphan, once])
    assert result.total == 2


def test_liked_mode_excludes_soft_deleted_from_count(session: Session, user: User) -> None:
    """A track only in a soft-deleted playlist counts as 0 memberships → orphan."""
    dead = _playlist(session, user, "Dead", deleted=True)
    t = _track(session, "t")
    _save(session, user, t)
    _add(session, user, dead, t, 0, BASE)
    session.commit()

    result = load_queue(
        session, user.id, QueueSource(liked=True, max_playlists=0), limit=10, offset=0
    )
    assert [e.track_id for e in result.items] == [t]
    assert result.total == 1


def test_liked_mode_excludes_removed(session: Session, user: User) -> None:
    t_active = _track(session, "active")
    t_removed = _track(session, "removed")
    _save(session, user, t_active)
    _save(session, user, t_removed, removed=True)
    session.commit()

    result = load_queue(
        session, user.id, QueueSource(liked=True, max_playlists=0), limit=10, offset=0
    )
    assert [e.track_id for e in result.items] == [t_active]
    assert result.total == 1


def test_liked_mode_pagination_stable_across_n(session: Session, user: User) -> None:
    """total + page boundaries are computed over the filtered set at each N."""
    gym = _playlist(session, user, "Gym")
    orphans = [_track(session, f"o{i}") for i in range(5)]
    filed = _track(session, "filed")
    for t in [*orphans, filed]:
        _save(session, user, t)
    _add(session, user, gym, filed, 0, BASE)
    session.commit()

    src = QueueSource(liked=True, max_playlists=0)
    page1 = load_queue(session, user.id, src, limit=2, offset=0)
    page2 = load_queue(session, user.id, src, limit=2, offset=2)
    page3 = load_queue(session, user.id, src, limit=2, offset=4)
    assert page1.total == page2.total == page3.total == 5  # filed excluded
    seen = [e.track_id for e in page1.items + page2.items + page3.items]
    assert sorted(seen) == sorted(orphans)  # every orphan, no overlap, no `filed`


# -- liked-mode ≤N filter counts only eligible playlists -----------------------


def test_track_only_in_excluded_playlist_is_an_orphan(session: Session, user: User) -> None:
    """A saved track living solely in an excluded playlist counts as 0 -> orphan."""
    excluded = _playlist(session, user, "Excluded")
    ex_row = session.get(Playlist, excluded)
    assert ex_row is not None
    ex_row.triage_excluded = True
    session.add(ex_row)

    orphan = _track(session, "orphan")  # in the excluded playlist only
    _add(session, user, excluded, orphan, 0, BASE)
    _save(session, user, orphan)
    session.commit()

    # N=0 (orphans): the track qualifies because its only membership is excluded.
    result = load_queue(
        session, user.id, QueueSource(liked=True, max_playlists=0), limit=10, offset=0
    )
    assert orphan in [e.track_id for e in result.items]
    assert result.total == 1


def test_eligible_membership_still_counts(session: Session, user: User) -> None:
    """A track in one eligible playlist is not an orphan at N=0, but is at N=1."""
    eligible = _playlist(session, user, "Eligible")
    excluded = _playlist(session, user, "Excluded")
    ex_row = session.get(Playlist, excluded)
    assert ex_row is not None
    ex_row.triage_excluded = True
    session.add(ex_row)

    t = _track(session, "t")
    _add(session, user, eligible, t, 0, BASE)  # one eligible membership
    _add(session, user, excluded, t, 0, BASE)  # plus an excluded one (ignored)
    _save(session, user, t)
    session.commit()

    # count = 1 (eligible only), so absent at N=0, present at N=1.
    at0 = load_queue(session, user.id, QueueSource(liked=True, max_playlists=0), limit=10, offset=0)
    assert t not in [e.track_id for e in at0.items]
    at1 = load_queue(session, user.id, QueueSource(liked=True, max_playlists=1), limit=10, offset=0)
    assert t in [e.track_id for e in at1.items]
