"""Bulk-algebra previews: set expressions, fingerprints, exact-delta apply."""

import pytest
from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import BulkOperation, MutationStatus
from crate.model.orm import MutationJournal, Playlist, User
from crate.services.mutations.algebra import (
    build_preview,
    library_fingerprint,
)
from crate.services.mutations.service import MutationService, track_uri
from tests.mutation_fakes import FakeSpotify
from tests.test_mutations_service import (
    local_order,
    seed_library,
    track_ids_for,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


def adds_of(manifest: dict, playlist_name: str) -> list[str]:
    for entry in manifest["entries"]:
        if entry["playlist_name"] == playlist_name:
            return [a["spotify_id"] for a in entry["adds"]]
    raise AssertionError(f"no entry for {playlist_name}")


def removes_of(manifest: dict, playlist_name: str) -> list[int]:
    for entry in manifest["entries"]:
        if entry["playlist_name"] == playlist_name:
            return [r["position"] for r in entry["removes"]]
    raise AssertionError(f"no entry for {playlist_name}")


# -- manifests -------------------------------------------------------------------


def test_union_into_new_playlist(session: Session, user: User, fake: FakeSpotify) -> None:
    seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Techno": ["t2", "t3"]})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.union,
        source_ids=[p.id for p in session.exec(select(Playlist)).all()],
        target_id=None,
        new_playlist_name="Peak Hours",
    )
    manifest = preview.manifest
    assert adds_of(manifest, "Peak Hours") == ["t1", "t2", "t3"]
    assert manifest["summary"] == {"adds": 3, "removes": 0, "playlists": 1}
    entry = manifest["entries"][0]
    assert entry["playlist_id"] is None and entry["new"] is True


def test_difference_manifest(session: Session, user: User, fake: FakeSpotify) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2", "t3"], "Drill": ["t2"], "Out": []})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.difference,
        source_ids=[lib["Gym"].id, lib["Drill"].id],
        target_id=lib["Out"].id,
        new_playlist_name=None,
    )
    assert adds_of(preview.manifest, "Out") == ["t1", "t3"]


def test_intersect_manifest(session: Session, user: User, fake: FakeSpotify) -> None:
    lib = seed_library(
        session, user, fake, {"A": ["t1", "t2", "t3"], "B": ["t2", "t3", "t4"], "Out": ["t9"]}
    )
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.intersect,
        source_ids=[lib["A"].id, lib["B"].id],
        target_id=lib["Out"].id,
        new_playlist_name=None,
    )
    # Target becomes exactly the expression result: t9 leaves, t2/t3 arrive.
    assert adds_of(preview.manifest, "Out") == ["t2", "t3"]
    assert removes_of(preview.manifest, "Out") == [0]


def test_dedupe_manifest_same_track_and_same_isrc(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    # t1 twice by id; t2/t2b share an ISRC under different Spotify ids.
    lib = seed_library(
        session,
        user,
        fake,
        {"Chill": ["t1", "t2", "t1", "t2b", "t3"]},
        isrc={"t2": "ISRC-SAME", "t2b": "ISRC-SAME"},
    )
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.dedupe,
        source_ids=[lib["Chill"].id],
        target_id=None,
        new_playlist_name=None,
    )
    # Keep first occurrences (positions 0, 1); drop the later duplicates.
    assert removes_of(preview.manifest, "Chill") == [2, 3]
    assert adds_of(preview.manifest, "Chill") == []


def test_sync_subset_to_parent_manifest(session: Session, user: User, fake: FakeSpotify) -> None:
    lib = seed_library(session, user, fake, {"Warmup": ["t1", "t2"], "Gym": ["t1", "t3"]})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.sync_subset_to_parent,
        source_ids=[lib["Warmup"].id],
        target_id=lib["Gym"].id,
        new_playlist_name=None,
    )
    assert adds_of(preview.manifest, "Gym") == ["t2"]
    assert removes_of(preview.manifest, "Gym") == []


# -- fingerprint -------------------------------------------------------------------


def test_fingerprint_stable_and_membership_sensitive(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    fp1 = library_fingerprint(session, user.id)
    assert fp1 == library_fingerprint(session, user.id)

    # Any membership change moves the fingerprint.
    from crate.model.orm import PlaylistTrack

    session.add(
        PlaylistTrack(
            user_id=user.id,
            playlist_id=lib["Pool"].id,
            track_id=track_ids_for(session, ["t1"])[0],
            position=1,
        )
    )
    session.commit()
    assert library_fingerprint(session, user.id) != fp1


# -- apply -------------------------------------------------------------------------


async def test_apply_preview_into_new_playlist(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Techno": ["t2", "t3"]})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.union,
        source_ids=[lib["Gym"].id, lib["Techno"].id],
        target_id=None,
        new_playlist_name="Peak Hours",
    )
    svc = MutationService(session=session, writer=fake, user=user)
    journal = await svc.apply_preview(preview)

    assert journal.status == MutationStatus.applied
    created = session.exec(select(Playlist).where(Playlist.name == "Peak Hours")).one()
    assert local_order(session, created.id) == ["t1", "t2", "t3"]
    assert fake.listing(created.spotify_id) == [track_uri(t) for t in ["t1", "t2", "t3"]]

    # Undo removes the created playlist again.
    await svc.undo(journal.id)
    session.refresh(created)
    assert created.is_deleted
    assert not fake.playlists[created.spotify_id].followed


async def test_apply_preview_dedupe_then_undo(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Chill": ["t1", "t2", "t1", "t3"]})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.dedupe,
        source_ids=[lib["Chill"].id],
        target_id=None,
        new_playlist_name=None,
    )
    svc = MutationService(session=session, writer=fake, user=user)
    journal = await svc.apply_preview(preview)

    assert local_order(session, lib["Chill"].id) == ["t1", "t2", "t3"]
    await svc.undo(journal.id)
    assert local_order(session, lib["Chill"].id) == ["t1", "t2", "t1", "t3"]
    assert fake.listing("sp-Chill") == [track_uri(t) for t in ["t1", "t2", "t1", "t3"]]


async def test_apply_is_exactly_the_previewed_delta(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    """Apply performs the stored manifest — nothing is recomputed at apply time."""
    lib = seed_library(session, user, fake, {"Warmup": ["t1"], "Gym": ["t2"], "Pool": ["t3"]})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.sync_subset_to_parent,
        source_ids=[lib["Warmup"].id],
        target_id=lib["Gym"].id,
        new_playlist_name=None,
    )
    # Tamper with the stored manifest to prove apply reads it verbatim.
    import copy

    manifest = copy.deepcopy(preview.manifest)
    entry = manifest["entries"][0]
    entry["adds"] = [
        {"track_id": track_ids_for(session, ["t3"])[0], "spotify_id": "t3", "name": "Track t3"}
    ]
    preview.manifest = manifest
    session.add(preview)
    session.commit()

    svc = MutationService(session=session, writer=fake, user=user)
    await svc.apply_preview(preview)
    assert local_order(session, lib["Gym"].id) == ["t2", "t3"]


async def test_apply_stale_preview_conflicts(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(session, user, fake, {"Gym": ["t1", "t2"], "Pool": ["t3"]})
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.sync_subset_to_parent,
        source_ids=[lib["Pool"].id],
        target_id=lib["Gym"].id,
        new_playlist_name=None,
    )
    # The library changes between preview and apply.
    svc = MutationService(session=session, writer=fake, user=user)
    await svc.add_tracks(lib["Gym"].id, track_ids_for(session, ["t3"]))

    with pytest.raises(AppError) as exc:
        await svc.apply_preview(preview)
    assert exc.value.status == 409
    assert exc.value.error_code == "PREVIEW_STALE"


async def test_partial_bulk_failure_records_per_entry_results_and_undoes(
    session: Session, user: User, fake: FakeSpotify
) -> None:
    lib = seed_library(
        session,
        user,
        fake,
        {"A": ["t1"], "B": ["t2"], "Src": ["t3"]},
    )
    # Expression adds t3 to both A and B (union of Src into each is modeled by
    # two entries via intersect? — use sync_subset twice is single-target, so
    # craft a manifest directly through two sequential previews is awkward;
    # instead: intersect with target A gives adds+removes across one entry.
    # For a genuine multi-entry manifest use dedupe across... simplest: build
    # a two-entry manifest by hand on a real preview row.
    preview = build_preview(
        session,
        user,
        operation=BulkOperation.sync_subset_to_parent,
        source_ids=[lib["Src"].id],
        target_id=lib["A"].id,
        new_playlist_name=None,
    )
    t3_id = track_ids_for(session, ["t3"])[0]
    manifest = {
        "entries": [
            {
                "playlist_id": lib["A"].id,
                "playlist_name": "A",
                "new": False,
                "adds": [{"track_id": t3_id, "spotify_id": "t3", "name": "Track t3"}],
                "removes": [],
            },
            {
                "playlist_id": lib["B"].id,
                "playlist_name": "B",
                "new": False,
                "adds": [{"track_id": t3_id, "spotify_id": "t3", "name": "Track t3"}],
                "removes": [],
            },
        ],
        "summary": {"adds": 2, "removes": 0, "playlists": 2},
    }
    preview.manifest = manifest
    session.add(preview)
    session.commit()

    fake.fail_after = 1  # entry A's single add succeeds; entry B's add fails
    svc = MutationService(session=session, writer=fake, user=user)
    journal = await svc.apply_preview(preview)

    assert journal.status == MutationStatus.partial
    results = journal.payload["results"]
    assert [r["status"] for r in results] == ["applied", "failed"]
    assert local_order(session, lib["A"].id) == ["t1", "t3"]
    assert local_order(session, lib["B"].id) == ["t2"]

    # Undo restores everything that did apply.
    fake.fail_after = None
    await svc.undo(journal.id)
    assert local_order(session, lib["A"].id) == ["t1"]
    assert fake.listing("sp-A") == [track_uri("t1")]
    assert local_order(session, lib["B"].id) == ["t2"]

    refreshed = session.get(MutationJournal, journal.id)
    assert refreshed is not None and refreshed.status == MutationStatus.undone
