"""Journal-first mutation core: apply → undo restores exact membership + order.

Every op type is exercised against the FakeSpotify state machine (real API
semantics) and the local database together: after undo, BOTH sides must equal
the pre-op state exactly.
"""

import random

import pytest
from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import (
    MutationOpType,
    MutationStatus,
    SyncEventSource,
    SyncEventType,
)
from crate.model.orm import (
    AnalyticsSnapshot,
    MutationJournal,
    Playlist,
    PlaylistTrack,
    SyncEvent,
    Track,
    User,
    utcnow,
)
from crate.services.mutations.service import MutationService, track_uri
from tests.mutation_fakes import FakeSpotify

pytestmark = pytest.mark.unit


# -- seeding -------------------------------------------------------------------


def seed_library(
    session: Session,
    user: User,
    fake: FakeSpotify,
    playlists: dict[str, list[str]],
    isrc: dict[str, str] | None = None,
) -> dict[str, Playlist]:
    """Create matching DB + fake-Spotify state. Track ids like "t1"."""
    isrc = isrc or {}
    track_rows: dict[str, Track] = {}
    for tids in playlists.values():
        for tid in tids:
            if tid in track_rows:
                continue
            row = Track(
                spotify_id=tid,
                name=f"Track {tid}",
                isrc=isrc.get(tid, f"ISRC-{tid}"),
                artists=[{"spotify_id": f"a-{tid}", "name": f"Artist {tid}"}],
                album_name="Album",
                duration_ms=200_000,
            )
            session.add(row)
            session.flush()
            track_rows[tid] = row

    result: dict[str, Playlist] = {}
    for name, tids in playlists.items():
        spotify_id = f"sp-{name}"
        playlist = Playlist(
            user_id=user.id,
            spotify_id=spotify_id,
            name=name,
            snapshot_id="snap-seed",
            is_owned=True,
        )
        session.add(playlist)
        session.flush()
        for position, tid in enumerate(tids):
            session.add(
                PlaylistTrack(
                    user_id=user.id,
                    playlist_id=playlist.id,
                    track_id=track_rows[tid].id,
                    position=position,
                    added_at=utcnow(),
                )
            )
        fake.seed(spotify_id, name, [track_uri(tid) for tid in tids])
        result[name] = playlist
    session.commit()
    return result


def local_order(session: Session, playlist_id: int) -> list[str]:
    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(PlaylistTrack.position)
    ).all()
    return [track.spotify_id for _, track in rows]


def track_ids_for(session: Session, spotify_ids: list[str]) -> list[int]:
    out: list[int] = []
    for sid in spotify_ids:
        row = session.exec(select(Track).where(Track.spotify_id == sid)).one()
        assert row.id is not None
        out.append(row.id)
    return out


def crate_events(session: Session) -> list[SyncEvent]:
    return list(
        session.exec(select(SyncEvent).where(SyncEvent.source == SyncEventSource.crate)).all()
    )


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


def service(session: Session, fake: FakeSpotify, user: User) -> MutationService:
    return MutationService(session=session, writer=fake, user=user)


# -- add_tracks -----------------------------------------------------------------


async def test_add_tracks_appends_and_journals(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    svc = service(session, fake, user)

    journal = await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t3"]))

    assert journal.status == MutationStatus.applied
    assert journal.op_type == MutationOpType.add_tracks
    assert journal.payload["playlist_name"] == "Gym"
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2", "t3"]]
    assert local_order(session, lib["Gym"].id) == ["t1", "t2", "t3"]

    events = crate_events(session)
    assert [e.event_type for e in events] == [SyncEventType.added]
    session.refresh(lib["Gym"])
    assert lib["Gym"].snapshot_id != "snap-seed"


async def test_add_tracks_at_position(session: Session, user: User, fake: FakeSpotify) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    svc = service(session, fake, user)

    await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t3"]), position=1)

    assert local_order(session, lib["Gym"].id) == ["t1", "t3", "t2"]
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t3", "t2"]]


async def test_add_tracks_invalidates_analytics_snapshots(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    session.add(AnalyticsSnapshot(user_id=user.id, kind="graph", payload={}))
    session.commit()
    svc = service(session, fake, user)

    await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t2"]))

    assert session.exec(select(AnalyticsSnapshot)).all() == []


async def test_add_tracks_leaves_track_map_snapshot_intact(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    """P1-4: a membership-only mutation must NOT evict the expensive track_map
    snapshot (it depends on the feature/track-set, not playlist membership) —
    otherwise the triage ritual storms background UMAP recomputes."""
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    session.add(AnalyticsSnapshot(user_id=user.id, kind="track_map", payload={"kept": True}))
    session.add(AnalyticsSnapshot(user_id=user.id, kind="graph", payload={}))
    session.commit()
    svc = service(session, fake, user)

    await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t2"]))

    kinds = {row.kind.value for row in session.exec(select(AnalyticsSnapshot)).all()}
    # Membership-dependent graph evicted; membership-independent track_map survives.
    assert "graph" not in kinds
    track_map = session.exec(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.kind == "track_map")
    ).one()
    assert track_map.payload == {"kept": True}


async def test_add_to_unknown_playlist_404s(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    seed_library(session, user, fake, {"Gym": ["t1"]})
    svc = service(session, fake, user)
    with pytest.raises(AppError) as exc:
        await svc.add_tracks(9999, track_ids_for(session, ["t1"]))
    assert exc.value.status == 404


# -- apply → undo property, every op type ----------------------------------------


async def test_add_then_undo_restores_exact_state(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    before_fake = fake.listing("sp-Gym")
    before_local = local_order(session, lib["Gym"].id)

    svc = service(session, fake, user)
    journal = await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t3"]), position=0)
    undone = await svc.undo(journal.id)

    assert undone.status == MutationStatus.undone
    assert undone.undone_at is not None
    assert fake.listing("sp-Gym") == before_fake
    assert local_order(session, lib["Gym"].id) == before_local


async def test_remove_then_undo_restores_exact_state(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3", "t4"]})
    before = local_order(session, lib["Gym"].id)

    svc = service(session, fake, user)
    journal = await svc.remove_tracks(lib["Gym"].id, positions=[1, 3])
    assert local_order(session, lib["Gym"].id) == ["t1", "t3"]
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t3"]]

    await svc.undo(journal.id)
    assert local_order(session, lib["Gym"].id) == before
    assert fake.listing("sp-Gym") == [track_uri(t) for t in before]


async def test_remove_single_occurrence_of_duplicate_then_undo(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    # t1 appears twice; removing position 2 must keep the position-0 copy.
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t1", "t3"]})
    svc = service(session, fake, user)

    journal = await svc.remove_tracks(lib["Gym"].id, positions=[2])
    assert local_order(session, lib["Gym"].id) == ["t1", "t2", "t3"]
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2", "t3"]]

    await svc.undo(journal.id)
    assert local_order(session, lib["Gym"].id) == ["t1", "t2", "t1", "t3"]
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2", "t1", "t3"]]


async def test_reorder_then_undo_restores_exact_order(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3", "t4"]})
    svc = service(session, fake, user)
    new_order = track_ids_for(session, ["t3", "t1", "t4", "t2"])

    journal = await svc.reorder(lib["Gym"].id, order=new_order)
    assert journal.op_type == MutationOpType.reorder
    assert local_order(session, lib["Gym"].id) == ["t3", "t1", "t4", "t2"]
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t3", "t1", "t4", "t2"]]

    await svc.undo(journal.id)
    assert local_order(session, lib["Gym"].id) == ["t1", "t2", "t3", "t4"]
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2", "t3", "t4"]]


async def test_reorder_emits_reordered_event_not_add_remove(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3"]})
    svc = service(session, fake, user)
    await svc.reorder(lib["Gym"].id, order=track_ids_for(session, ["t3", "t2", "t1"]))
    events = crate_events(session)
    assert [e.event_type for e in events] == [SyncEventType.reordered]


async def test_reorder_rejects_non_permutation(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    svc = service(session, fake, user)
    with pytest.raises(AppError) as exc:
        await svc.reorder(lib["Gym"].id, order=track_ids_for(session, ["t1", "t3"]))
    assert exc.value.status == 409
    assert exc.value.error_code == "ORDER_STALE"
    # Nothing journaled, nothing changed.
    assert session.exec(select(MutationJournal)).all() == []
    assert local_order(session, lib["Gym"].id) == ["t1", "t2"]


async def test_remove_rejects_out_of_range_positions(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"]})
    svc = service(session, fake, user)
    with pytest.raises(AppError) as exc:
        await svc.remove_tracks(lib["Gym"].id, positions=[5])
    assert exc.value.status == 409
    assert exc.value.error_code == "MEMBERSHIP_STALE"


async def test_create_playlist_then_undo_unfollows(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    seed_library(session, user, fake, {"Gym": ["t1"]})
    svc = service(session, fake, user)

    journal = await svc.create_playlist("Peak Hours", description="bulk target")
    assert journal.op_type == MutationOpType.create_playlist
    playlist_id = journal.payload["playlist_id"]
    row = session.get(Playlist, playlist_id)
    assert row is not None and row.name == "Peak Hours" and not row.is_deleted
    assert fake.playlists[row.spotify_id].followed

    await svc.undo(journal.id)
    session.refresh(row)
    assert row.is_deleted
    assert not fake.playlists[row.spotify_id].followed


async def test_rename_then_undo_restores_name_and_description(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"]})
    lib["Gym"].description = "old description"
    session.add(lib["Gym"])
    session.commit()
    fake.playlists["sp-Gym"].description = "old description"
    svc = service(session, fake, user)

    journal = await svc.rename_playlist(lib["Gym"].id, name="Iron Temple", description="new")
    session.refresh(lib["Gym"])
    assert lib["Gym"].name == "Iron Temple"
    assert lib["Gym"].description == "new"
    assert fake.playlists["sp-Gym"].name == "Iron Temple"

    await svc.undo(journal.id)
    session.refresh(lib["Gym"])
    assert lib["Gym"].name == "Gym"
    assert lib["Gym"].description == "old description"
    assert fake.playlists["sp-Gym"].name == "Gym"
    assert fake.playlists["sp-Gym"].description == "old description"


async def test_rename_emits_renamed_event(session: Session, user: User, fake: FakeSpotify) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"]})
    svc = service(session, fake, user)
    await svc.rename_playlist(lib["Gym"].id, name="Iron Temple")
    events = crate_events(session)
    assert [e.event_type for e in events] == [SyncEventType.playlist_renamed]
    assert events[0].detail == {"from": "Gym", "to": "Iron Temple"}


# -- undo guards -----------------------------------------------------------------


async def test_undo_twice_conflicts(session: Session, user: User, fake: FakeSpotify) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1"], "Pool": ["t2"]})
    svc = service(session, fake, user)
    journal = await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t2"]))
    await svc.undo(journal.id)
    with pytest.raises(AppError) as exc:
        await svc.undo(journal.id)
    assert exc.value.status == 409
    assert exc.value.error_code == "NOT_UNDOABLE"


async def test_undo_unknown_journal_404s(session: Session, user: User, fake: FakeSpotify) -> None:
    svc = service(session, fake, user)
    with pytest.raises(AppError) as exc:
        await svc.undo(12345)
    assert exc.value.status == 404


# -- failure handling --------------------------------------------------------------


async def test_write_failure_marks_partial_and_self_heals_local(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    svc = service(session, fake, user)
    fake.fail_after = 0  # first write call fails

    with pytest.raises(AppError) as exc:
        await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t3"]))
    assert exc.value.status == 502
    assert exc.value.error_code == "SPOTIFY_WRITE_FAILED"

    journal = session.exec(select(MutationJournal)).one()
    assert journal.status == MutationStatus.partial
    # Nothing applied remotely, local mirrors remote.
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2"]]
    assert local_order(session, lib["Gym"].id) == ["t1", "t2"]

    # A partial journal entry is undoable and restores the original state.
    fake.fail_after = None
    await svc.undo(journal.id)
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2"]]
    assert local_order(session, lib["Gym"].id) == ["t1", "t2"]


async def test_mid_plan_failure_self_heals_local_to_remote(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    # Removing one occurrence of a duplicate = remove-all then re-add. Failing
    # the re-add leaves remote half-changed; local must mirror the actual
    # remote state, and undo must restore the original.
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t1", "t3"]})
    svc = service(session, fake, user)
    fake.fail_after = 1  # the remove succeeds, the re-add fails

    with pytest.raises(AppError):
        await svc.remove_tracks(lib["Gym"].id, positions=[2])

    # Remote lost both t1 occurrences; local reflects reality.
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t2", "t3"]]
    assert local_order(session, lib["Gym"].id) == ["t2", "t3"]

    journal = session.exec(select(MutationJournal)).one()
    assert journal.status == MutationStatus.partial

    fake.fail_after = None
    await svc.undo(journal.id)
    assert fake.listing("sp-Gym") == [track_uri(t) for t in ["t1", "t2", "t1", "t3"]]
    assert local_order(session, lib["Gym"].id) == ["t1", "t2", "t1", "t3"]


# -- randomized state machine over every membership op type ------------------------


async def test_random_op_sequences_undo_to_origin(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    """Apply a random op, undo it, assert exact restoration — repeatedly."""
    rng = random.Random(2026)
    tids = [f"t{i}" for i in range(8)]
    lib = seed_library(
        session,
        user,
        fake,
        {"A": ["t0", "t1", "t2", "t3"], "B": ["t2", "t4", "t5"], "Pool": tids},
    )
    svc = service(session, fake, user)

    for _ in range(25):
        name = rng.choice(["A", "B"])
        playlist = lib[name]
        spid = playlist.spotify_id
        before_fake = fake.listing(spid)
        before_local = local_order(session, playlist.id)

        n = len(before_local)
        op = rng.choice(["add", "remove", "reorder"])
        if op == "add":
            picks = rng.sample(tids, k=rng.randint(1, 3))
            position = rng.choice([None, rng.randint(0, n)])
            journal = await svc.add_tracks(
                playlist.id, track_ids_for(session, picks), position=position
            )
        elif op == "remove" and n > 0:
            k = rng.randint(1, min(2, n))
            positions = rng.sample(range(n), k=k)
            journal = await svc.remove_tracks(playlist.id, positions=positions)
        elif op == "reorder" and n > 1:
            order_sids = before_local[:]
            rng.shuffle(order_sids)
            journal = await svc.reorder(playlist.id, order=track_ids_for(session, order_sids))
        else:
            continue

        await svc.undo(journal.id)
        assert fake.listing(spid) == before_fake, f"fake diverged after {op} on {name}"
        assert local_order(session, playlist.id) == before_local, (
            f"local diverged after {op} on {name}"
        )
