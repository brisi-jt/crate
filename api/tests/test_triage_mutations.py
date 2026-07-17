"""Triage write path: journaled unsave, the composite file_track filing, and
the P0-3 resurrection guarantee — the Spotify DELETE lands before the local
is_removed flip, so a sync between the two can never resurrect the like.
"""

import pytest
from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import MutationOpType, MutationStatus
from crate.model.orm import MutationJournal, Playlist, SavedTrack, Track, User, utcnow
from crate.services.account.saved import sync_saved_tracks
from crate.services.mutations.service import MutationService
from crate.services.spotify.models import SpotifyTrack
from tests.mutation_fakes import FakeSpotify
from tests.test_mutations_service import local_order, seed_library, track_ids_for

pytestmark = pytest.mark.unit


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


def service(session: Session, fake: FakeSpotify, user: User) -> MutationService:
    return MutationService(session=session, writer=fake, user=user)


def _save_row(session: Session, user: User, spotify_id: str) -> SavedTrack:
    track = session.exec(select(Track).where(Track.spotify_id == spotify_id)).one()
    assert track.id is not None
    row = SavedTrack(user_id=user.id, track_id=track.id, saved_at=utcnow())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


class RemoteSavedReader:
    """A SavedTracksReader over the FakeSpotify remote saved set."""

    def __init__(self, fake: FakeSpotify) -> None:
        self._fake = fake

    async def iter_saved_tracks(self):
        for sid in sorted(self._fake.saved):
            yield type(
                "Item",
                (),
                {
                    "track": SpotifyTrack.model_validate(
                        {"id": sid, "name": f"Track {sid}", "artists": [], "album": None}
                    ),
                    "added_at": None,
                },
            )()


# -- journaled unsave ----------------------------------------------------------


async def test_unsave_tracks_journals_and_flips_local(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    seed_library(session, user, fake, {"Gym": ["t1", "t2"]})
    fake.seed_saved("t1", "t2")
    _save_row(session, user, "t1")
    _save_row(session, user, "t2")

    journal = await service(session, fake, user).unsave_tracks(track_ids_for(session, ["t1"]))

    assert journal.op_type == MutationOpType.unsave_track
    assert journal.status == MutationStatus.applied
    # Remote Liked Songs no longer holds t1; t2 untouched.
    assert fake.saved == {"t2"}
    row = session.exec(
        select(SavedTrack).where(SavedTrack.track_id == track_ids_for(session, ["t1"])[0])
    ).one()
    assert row.is_removed is True
    assert row.removed_at is not None


async def test_unsave_undo_re_saves(session: Session, user: User, fake: FakeSpotify) -> None:
    seed_library(session, user, fake, {"Gym": ["t1"]})
    fake.seed_saved("t1")
    _save_row(session, user, "t1")

    svc = service(session, fake, user)
    journal = await svc.unsave_tracks(track_ids_for(session, ["t1"]))
    await svc.undo(journal.id)

    # Undo re-saves remotely AND reactivates the local row.
    assert fake.saved == {"t1"}
    row = session.exec(select(SavedTrack).where(SavedTrack.user_id == user.id)).one()
    assert row.is_removed is False
    assert row.removed_at is None


# -- P0-3: ordering / resurrection ---------------------------------------------


async def test_unsave_remote_failure_does_not_flip_local(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    """If the Spotify DELETE fails, the local is_removed flip must NOT commit —
    otherwise the row is locally-removed but still remote, and the next sync
    resurrects it (P0-3)."""
    seed_library(session, user, fake, {"Gym": ["t1"]})
    fake.seed_saved("t1")
    _save_row(session, user, "t1")
    fake.fail_after = 0  # the very first write raises

    with pytest.raises(AppError) as exc:
        await service(session, fake, user).unsave_tracks(track_ids_for(session, ["t1"]))
    assert exc.value.status == 502

    # Remote still holds t1 (delete failed) AND local row is NOT removed — the
    # two agree, so a sync leaves it saved. No resurrection window.
    assert fake.saved == {"t1"}
    row = session.exec(select(SavedTrack).where(SavedTrack.user_id == user.id)).one()
    assert row.is_removed is False


async def test_unsave_then_sync_stays_removed(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    """Unsave, then run the real saved-tracks sync against the remote the unsave
    mutated. The track is gone remotely, so the sync leaves it removed — no
    resurrection (P0-3 test a)."""
    seed_library(session, user, fake, {"Gym": ["t1", "t2"]})
    fake.seed_saved("t1", "t2")
    _save_row(session, user, "t1")
    _save_row(session, user, "t2")

    await service(session, fake, user).unsave_tracks(track_ids_for(session, ["t1"]))
    report = await sync_saved_tracks(session, RemoteSavedReader(fake), user)

    # The sync saw t2 (still remote) and NOT t1 (unsaved) — t1 stays removed.
    assert report.removed == 0  # already removed by the unsave; not re-removed
    t1_id = track_ids_for(session, ["t1"])[0]
    row = session.exec(select(SavedTrack).where(SavedTrack.track_id == t1_id)).one()
    assert row.is_removed is True


# -- composite file_track (P0-1 / P0-2) ----------------------------------------


async def test_file_track_adds_to_multiple_playlists_one_journal(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"], "Focus": []})
    t3 = track_ids_for(session, ["t1"])[0]  # reuse t1 as the track being filed
    # File t2 into Gym and Focus.
    filed = track_ids_for(session, ["t2"])[0]

    before = session.exec(select(MutationJournal)).all()
    journal = await service(session, fake, user).file_track(
        track_id=filed,
        destination_playlist_ids=track_playlist_ids(session, ["Gym", "Focus"]),
        new_playlist=None,
        unsave=False,
    )
    after = session.exec(select(MutationJournal)).all()

    assert len(after) - len(before) == 1  # ONE journal entry for the whole filing
    assert journal.op_type == MutationOpType.file_track
    assert journal.status == MutationStatus.applied
    assert local_order(session, playlist_id(session, "Gym")) == ["t1", "t2"]
    assert local_order(session, playlist_id(session, "Focus")) == ["t2"]
    _ = t3


async def test_file_track_with_unsave_undo_restores_both(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    """Apply {add to 2 playlists + unsave}, undo, assert BOTH playlist orderings
    restored AND the track re-saved (P0-2)."""
    seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    fake.seed_saved("t3")
    # add t3 to the catalog + saved
    track = Track(spotify_id="t3", name="Track t3", artists=[{"spotify_id": "a-t3", "name": "A3"}])
    session.add(track)
    session.commit()
    session.refresh(track)
    assert track.id is not None
    _save_row(session, user, "t3")

    svc = service(session, fake, user)
    journal = await svc.file_track(
        track_id=track.id,
        destination_playlist_ids=track_playlist_ids(session, ["Gym", "Pool"]),
        new_playlist=None,
        unsave=True,
    )
    assert local_order(session, playlist_id(session, "Gym")) == ["t1", "t3"]
    assert local_order(session, playlist_id(session, "Pool")) == ["t2", "t3"]
    assert fake.saved == set()  # unsaved

    await svc.undo(journal.id)

    # Both playlists back to pre-filing order AND the track re-saved.
    assert local_order(session, playlist_id(session, "Gym")) == ["t1"]
    assert local_order(session, playlist_id(session, "Pool")) == ["t2"]
    assert fake.saved == {"t3"}
    row = session.exec(select(SavedTrack).where(SavedTrack.track_id == track.id)).one()
    assert row.is_removed is False


async def test_file_track_new_playlist_seeds_cluster_and_undo_removes_it(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3"]})
    seed = track_ids_for(session, ["t1", "t2"])
    filed = track_ids_for(session, ["t3"])[0]

    svc = service(session, fake, user)
    journal = await svc.file_track(
        track_id=filed,
        destination_playlist_ids=[],
        new_playlist={"name": "Late Night", "seed_track_ids": seed},
        unsave=False,
    )
    # New playlist exists with the filed track + its seed cluster.
    new_pl = session.exec(select(Playlist).where(Playlist.name == "Late Night")).one()
    assert new_pl.id is not None
    assert sorted(local_order(session, new_pl.id)) == sorted(["t1", "t2", "t3"])

    await svc.undo(journal.id)
    session.refresh(new_pl)
    assert new_pl.is_deleted is True


# -- helpers -------------------------------------------------------------------


def playlist_id(session: Session, name: str) -> int:
    row = session.exec(select(Playlist).where(Playlist.name == name)).one()
    assert row.id is not None
    return row.id


def track_playlist_ids(session: Session, names: list[str]) -> list[int]:
    return [playlist_id(session, name) for name in names]
