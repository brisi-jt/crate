"""Suggestion queue: ranked ordering from live DB state + the feedback loop.

The feedback-loop property: rejecting an artist's track strictly lowers that
artist's rank in the next batch.
"""

import pytest
from sqlmodel import Session, select

from crate.model.enums import CandidateSource, CandidateStatus, FeedbackAction
from crate.model.orm import DiscoveryCandidate, Playlist, SuggestionFeedback, User
from crate.services.discovery.generation import dedup_key
from crate.services.discovery.service import build_suggestion_queue, record_feedback
from tests.discovery_fakes import seed_playlist

pytestmark = pytest.mark.unit

# Feature profiles: the playlist is high-energy electronic; candidate features
# are raw values ranked against this library's distribution.
HOT = {"energy": 0.9, "valence": 0.6, "danceability": 0.85, "acousticness": 0.05}
WARM = {"energy": 0.7, "valence": 0.55, "danceability": 0.7, "acousticness": 0.2}
COLD = {"energy": 0.2, "valence": 0.3, "danceability": 0.3, "acousticness": 0.9}


@pytest.fixture
def gym(session: Session, user: User) -> Playlist:
    return seed_playlist(
        session,
        user,
        "Gym",
        [
            ("t-a", "Track A", "KREAM"),
            ("t-b", "Track B", "KREAM"),
            ("t-c", "Track C", "Skrillex"),
            ("t-cold", "Slow One", "Bon Iver"),
        ],
        features={"t-a": HOT, "t-b": HOT, "t-c": WARM, "t-cold": COLD},
    )


def add_candidate(
    session: Session,
    user: User,
    playlist: Playlist,
    title: str,
    artist: str,
    features: dict[str, float] | None,
    status: CandidateStatus = CandidateStatus.resolved,
) -> DiscoveryCandidate:
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        status=status,
        title=title,
        artist=artist,
        dedup_key=dedup_key(title, artist),
        spotify_id=f"sp-{dedup_key(title, artist)}"[:64],
        features=features,
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def test_queue_ranks_acoustically_close_candidates_first(
    session: Session, user: User, gym: Playlist
) -> None:
    close = add_candidate(session, user, gym, "Close", "Cassian", HOT)
    far = add_candidate(session, user, gym, "Far", "Iron & Wine", COLD)

    queue = build_suggestion_queue(session, user, gym)

    assert [entry.candidate.id for entry in queue] == [close.id, far.id]
    assert queue[0].breakdown.fit > queue[1].breakdown.fit


def test_queue_is_deterministic(session: Session, user: User, gym: Playlist) -> None:
    add_candidate(session, user, gym, "Close", "Cassian", HOT)
    add_candidate(session, user, gym, "Mid", "Overmono", WARM)
    add_candidate(session, user, gym, "Far", "Iron & Wine", COLD)

    first = [(e.candidate.id, e.breakdown.fit) for e in build_suggestion_queue(session, user, gym)]
    second = [(e.candidate.id, e.breakdown.fit) for e in build_suggestion_queue(session, user, gym)]
    assert first == second


def test_queue_only_serves_resolved_candidates(session: Session, user: User, gym: Playlist) -> None:
    served = add_candidate(session, user, gym, "Served", "Cassian", HOT)
    add_candidate(session, user, gym, "Pending", "X", HOT, status=CandidateStatus.pending)
    add_candidate(session, user, gym, "Gone", "Y", HOT, status=CandidateStatus.rejected)
    add_candidate(session, user, gym, "Done", "Z", HOT, status=CandidateStatus.accepted)

    queue = build_suggestion_queue(session, user, gym)
    assert [entry.candidate.id for entry in queue] == [served.id]


def test_queue_entry_carries_fingerprint_vs_playlist(
    session: Session, user: User, gym: Playlist
) -> None:
    add_candidate(session, user, gym, "Close", "Cassian", HOT)
    entry = build_suggestion_queue(session, user, gym)[0]
    features = {row["feature"] for row in entry.fingerprint}
    assert {"energy", "valence", "acousticness"} <= features
    for row in entry.fingerprint:
        assert 0.0 <= row["candidate"] <= 1.0
        assert 0.0 <= row["playlist"] <= 1.0


def test_featureless_candidate_still_ranks(session: Session, user: User, gym: Playlist) -> None:
    add_candidate(session, user, gym, "Mystery", "Unknown", None)
    queue = build_suggestion_queue(session, user, gym)
    assert len(queue) == 1
    assert 0.0 <= queue[0].breakdown.fit <= 1.0


# ------------------------------------------------------------- feedback loop


def test_rejected_artist_rank_strictly_decreases_next_batch(
    session: Session, user: User, gym: Playlist
) -> None:
    """Reject a Cassian track; the next Cassian candidate must rank lower."""
    cassian_1 = add_candidate(session, user, gym, "Magical", "Cassian", HOT)
    rival = add_candidate(session, user, gym, "Rival", "Overmono", HOT)

    first_queue = build_suggestion_queue(session, user, gym)
    first_fit = {e.candidate.id: e.breakdown.fit for e in first_queue}
    # Same features -> identical acoustics; ids break the tie, Cassian first.
    assert [e.candidate.id for e in first_queue] == [cassian_1.id, rival.id]

    record_feedback(session, user, cassian_1, FeedbackAction.reject)
    assert cassian_1.status == CandidateStatus.rejected

    # Next batch proposes another Cassian track.
    cassian_2 = add_candidate(session, user, gym, "Same Things", "Cassian", HOT)
    second_queue = build_suggestion_queue(session, user, gym)

    ranks = [e.candidate.id for e in second_queue]
    assert ranks == [rival.id, cassian_2.id], "rejected artist must fall below the rival"
    cassian_2_fit = next(e.breakdown.fit for e in second_queue if e.candidate.id == cassian_2.id)
    assert cassian_2_fit < first_fit[cassian_1.id]


def test_skip_records_feedback_but_keeps_candidate_in_queue(
    session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(session, user, gym, "Maybe", "Cassian", HOT)
    record_feedback(session, user, candidate, FeedbackAction.skip)

    assert candidate.status == CandidateStatus.resolved
    feedback = session.exec(
        select(SuggestionFeedback).where(SuggestionFeedback.candidate_id == candidate.id)
    ).one()
    assert feedback.action == FeedbackAction.skip
    assert [e.candidate.id for e in build_suggestion_queue(session, user, gym)] == [candidate.id]


def test_accepts_lift_the_artists_future_fit(session: Session, user: User, gym: Playlist) -> None:
    liked = add_candidate(session, user, gym, "Liked", "Cassian", HOT)
    baseline = build_suggestion_queue(session, user, gym)[0].breakdown.fit

    session.add(
        SuggestionFeedback(
            user_id=user.id,
            candidate_id=liked.id,
            playlist_id=gym.id,
            artist="Cassian",
            action=FeedbackAction.accept,
        )
    )
    session.commit()

    lifted = build_suggestion_queue(session, user, gym)[0].breakdown.fit
    assert lifted > baseline
