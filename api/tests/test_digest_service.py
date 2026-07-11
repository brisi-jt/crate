"""Weekly digest generation — window math, section building, regeneration."""

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from crate.model.enums import (
    CandidateSource,
    CandidateStatus,
    DigestSection,
    FeedbackAction,
    SnapshotKind,
    SyncEventType,
)
from crate.model.orm import (
    AnalyticsSnapshot,
    DigestItem,
    DiscoveryCandidate,
    FeatureCalibration,
    PlayEvent,
    Playlist,
    SuggestionFeedback,
    SyncEvent,
    Track,
    User,
)
from crate.services.digest.service import (
    generate_digest,
    run_weekly_digest_for_user,
    week_start_for,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 9, 15, 0)  # a Thursday
WEEK_START = datetime(2026, 7, 6)  # the Monday of that week


def seed_playlist(session: Session, user: User, name: str, *, owned: bool = True) -> Playlist:
    playlist = Playlist(
        user_id=user.id, spotify_id=f"sp-{name}", name=name, is_owned=owned, snapshot_id="s1"
    )
    session.add(playlist)
    session.flush()
    return playlist


def seed_track(session: Session, spotify_id: str, *, name: str | None = None) -> Track:
    track = Track(
        spotify_id=spotify_id,
        name=name or f"Track {spotify_id}",
        artists=[{"spotify_id": None, "name": f"Artist {spotify_id}"}],
    )
    session.add(track)
    session.flush()
    return track


def seed_candidate(
    session: Session,
    user: User,
    playlist: Playlist,
    title: str,
    *,
    created_at: datetime,
    status: CandidateStatus = CandidateStatus.resolved,
    features: dict | None = None,
) -> DiscoveryCandidate:
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        status=status,
        title=title,
        artist=f"{title} Artist",
        dedup_key=f"{title.casefold()}|{playlist.id}",
        spotify_id=f"cand-{title}",
        features=features,
    )
    candidate.created_at = created_at
    session.add(candidate)
    session.flush()
    return candidate


def extra_of(item: DigestItem) -> dict:
    assert item.extra is not None
    return item.extra


def items_by_section(session: Session, digest_id: int) -> dict[DigestSection, list[DigestItem]]:
    rows = session.exec(
        select(DigestItem).where(DigestItem.digest_id == digest_id).order_by(DigestItem.position)  # type: ignore[arg-type]
    ).all()
    grouped: dict[DigestSection, list[DigestItem]] = {}
    for row in rows:
        grouped.setdefault(row.section, []).append(row)
    return grouped


# --- week math ---------------------------------------------------------------


def test_week_start_is_most_recent_monday_midnight() -> None:
    assert week_start_for(NOW) == WEEK_START
    # A Monday maps to itself.
    assert week_start_for(datetime(2026, 7, 6, 4, 59)) == WEEK_START
    # Sunday belongs to the week that started six days earlier.
    assert week_start_for(datetime(2026, 7, 12, 23, 59)) == WEEK_START


# --- section building ---------------------------------------------------------


def test_suggestion_counts_grouped_by_playlist(session: Session, user: User) -> None:
    gym = seed_playlist(session, user, "Gym")
    chill = seed_playlist(session, user, "Chill")
    for index in range(3):
        seed_candidate(session, user, gym, f"g{index}", created_at=WEEK_START + timedelta(days=1))
    seed_candidate(session, user, chill, "c0", created_at=WEEK_START + timedelta(days=2))
    # Outside the window: never counted.
    seed_candidate(session, user, gym, "old", created_at=WEEK_START - timedelta(days=1))
    session.commit()

    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)

    assert digest.id is not None
    suggestions = items_by_section(session, digest.id)[DigestSection.suggestions]
    assert [(item.title, extra_of(item)["count"]) for item in suggestions] == [
        ("Gym", 3),
        ("Chill", 1),
    ]
    assert suggestions[0].playlist_id == gym.id


def test_followed_playlists_stay_out_of_the_digest(session: Session, user: User) -> None:
    followed = seed_playlist(session, user, "Followed", owned=False)
    seed_candidate(session, user, followed, "f0", created_at=WEEK_START + timedelta(days=1))
    session.commit()

    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)

    assert digest.id is not None
    assert DigestSection.suggestions not in items_by_section(session, digest.id)


def test_top_unheard_candidates_exclude_reviewed_ones(session: Session, user: User) -> None:
    gym = seed_playlist(session, user, "Gym")
    for feature in ("energy", "valence"):
        session.add(FeatureCalibration(feature=feature, p10=0.1, p50=0.5, p90=0.9, sample_size=4))
    heard = seed_candidate(
        session,
        user,
        gym,
        "heard",
        created_at=WEEK_START + timedelta(days=1),
        features={"energy": 0.9},
    )
    seed_candidate(
        session,
        user,
        gym,
        "fresh",
        created_at=WEEK_START + timedelta(days=1),
        features={"energy": 0.8},
    )
    session.add(
        SuggestionFeedback(
            user_id=user.id,
            candidate_id=heard.id,
            playlist_id=gym.id,
            artist=heard.artist,
            action=FeedbackAction.skip,
        )
    )
    session.commit()

    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)

    assert digest.id is not None
    candidates = items_by_section(session, digest.id)[DigestSection.candidates]
    assert [item.title for item in candidates] == ["fresh — fresh Artist"]
    assert candidates[0].candidate_id is not None
    assert candidates[0].playlist_id == gym.id
    assert 0.0 <= extra_of(candidates[0])["fit"] <= 1.0


def test_library_changes_summarized_from_sync_events(session: Session, user: User) -> None:
    gym = seed_playlist(session, user, "Gym")
    track = seed_track(session, "t1")
    for _ in range(2):
        session.add(
            SyncEvent(
                user_id=user.id,
                playlist_id=gym.id,
                track_id=track.id,
                event_type=SyncEventType.added,
                observed_at=WEEK_START + timedelta(days=2),
            )
        )
    session.add(
        SyncEvent(
            user_id=user.id,
            playlist_id=gym.id,
            track_id=track.id,
            event_type=SyncEventType.removed,
            observed_at=WEEK_START + timedelta(days=3),
        )
    )
    # Outside the window.
    session.add(
        SyncEvent(
            user_id=user.id,
            playlist_id=gym.id,
            track_id=track.id,
            event_type=SyncEventType.added,
            observed_at=WEEK_START - timedelta(days=2),
        )
    )
    session.commit()

    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)

    assert digest.id is not None
    library = items_by_section(session, digest.id)[DigestSection.library]
    assert len(library) == 1
    assert library[0].title == "Gym"
    assert library[0].extra == {"added": 2, "removed": 1}
    assert library[0].playlist_id == gym.id


def test_listening_notes_only_when_plays_exist(session: Session, user: User) -> None:
    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert digest.id is not None
    assert DigestSection.listening not in items_by_section(session, digest.id)

    track = seed_track(session, "hit", name="Hit Song")
    for hour in range(3):
        session.add(
            PlayEvent(
                user_id=user.id,
                track_id=track.id,
                played_at=WEEK_START + timedelta(days=1, hours=hour),
            )
        )
    session.commit()

    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert digest.id is not None
    listening = items_by_section(session, digest.id)[DigestSection.listening]
    assert len(listening) == 1
    assert extra_of(listening[0])["plays"] == 3
    assert "Hit Song" in (listening[0].body or "")


def test_frontier_movement_against_previous_digest(session: Session, user: User) -> None:
    # Cached frontier payload — generate_digest reads through the snapshot cache.
    session.add(
        AnalyticsSnapshot(
            user_id=user.id,
            kind=SnapshotKind.frontier,
            owned_only=True,
            payload={
                "territory": [],
                "frontier": [
                    {"genre_id": 1, "name": "trip hop", "score": 2.3},
                    {"genre_id": 2, "name": "float house", "score": 1.1},
                ],
                "coverage": {"library_artists": 0, "matched_artists": 0},
            },
        )
    )
    session.commit()

    # First digest: no previous reading — the top genres appear as fresh reads.
    first = generate_digest(session, user, week_start=WEEK_START - timedelta(days=7), now=NOW)
    assert first.id is not None
    frontier_items = items_by_section(session, first.id)[DigestSection.frontier]
    assert {item.genre for item in frontier_items} == {"trip hop", "float house"}
    assert first.meta["frontier_top"][0]["name"] == "trip hop"

    # Second week: same frontier — no movement, no items.
    second = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert second.id is not None
    assert DigestSection.frontier not in items_by_section(session, second.id)

    # Frontier shifts: only the new entrant is reported.
    snapshot = session.exec(select(AnalyticsSnapshot)).one()
    snapshot.payload = {
        "territory": [],
        "frontier": [
            {"genre_id": 3, "name": "chamber pop", "score": 3.0},
            {"genre_id": 1, "name": "trip hop", "score": 2.3},
        ],
        "coverage": {"library_artists": 0, "matched_artists": 0},
    }
    session.add(snapshot)
    session.commit()

    third = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert third.id is not None
    moved = items_by_section(session, third.id)[DigestSection.frontier]
    assert [item.genre for item in moved] == ["chamber pop"]


# --- regeneration -------------------------------------------------------------


def test_regenerating_a_week_replaces_items_and_resets_read(session: Session, user: User) -> None:
    gym = seed_playlist(session, user, "Gym")
    seed_candidate(session, user, gym, "g0", created_at=WEEK_START + timedelta(days=1))
    session.commit()

    first = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert first.id is not None
    first.read_at = NOW
    session.add(first)
    session.commit()

    seed_candidate(session, user, gym, "g1", created_at=WEEK_START + timedelta(days=2))
    session.commit()

    second = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert second.id == first.id  # same row, rebuilt
    assert second.read_at is None  # fresh content reads as unread
    suggestions = items_by_section(session, second.id)[DigestSection.suggestions]
    assert extra_of(suggestions[0])["count"] == 2
    # No orphaned items from the first build.
    total_items = len(session.exec(select(DigestItem)).all())
    by_section = items_by_section(session, second.id)
    assert total_items == sum(len(v) for v in by_section.values())


def test_empty_week_still_produces_a_digest(session: Session, user: User) -> None:
    digest = generate_digest(session, user, week_start=WEEK_START, now=NOW)
    assert digest.id is not None
    assert items_by_section(session, digest.id) == {}
    assert digest.week_start == WEEK_START


# --- scheduled entry point ------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_run_covers_the_completed_week_and_skips_existing(
    session: Session, user: User
) -> None:
    generated = await run_weekly_digest_for_user(session, user, now=NOW)
    assert generated is not None
    assert generated.week_start == WEEK_START - timedelta(days=7)

    again = await run_weekly_digest_for_user(session, user, now=NOW)
    assert again is None  # already on file — the scheduled pass never regenerates
