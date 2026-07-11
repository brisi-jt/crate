"""Suggestion queue assembly, feedback recording, and the accept path.

The queue is recomputed from the database on every read: candidate features
are ranked against the current library percentile space, artist affinity
against the current similarity edges, and feedback against the full decision
history — so every accept/reject immediately reshapes the next queue.
"""

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, col, select

from crate.model.enums import CandidateStatus, FeedbackAction
from crate.model.orm import (
    Artist,
    ArtistSimilarity,
    DiscoveryCandidate,
    Playlist,
    PlaylistTrack,
    SuggestionFeedback,
    Track,
    User,
)
from crate.services.analytics.loaders import load_library, load_percentile_space
from crate.services.discovery.ranker import FitBreakdown, RankInput, rank
from crate.services.mutations.service import MutationService
from crate.services.mutations.writer import SpotifyWriter

# The three features the deck's fingerprint compares against the playlist.
FINGERPRINT_FEATURES = ("energy", "valence", "acousticness")


@dataclass
class QueueEntry:
    candidate: DiscoveryCandidate
    breakdown: FitBreakdown
    # [{feature, candidate, playlist}] percentile pairs for the deck bars.
    fingerprint: list[dict[str, Any]]


def _playlist_centroid(
    session: Session, user: User, playlist: Playlist
) -> tuple[dict[str, float], Any]:
    """(centroid percentile vector, percentile space) for the playlist."""
    assert user.id is not None
    space = load_percentile_space(session)
    library = load_library(session, user.id)
    members = library.memberships.get(playlist.id or 0, set())
    vectors = [
        space.transform(library.features[tid]) for tid in sorted(members) if tid in library.features
    ]
    if not vectors:
        return {}, space
    centroid = {
        feature: sum(vector[feature] for vector in vectors) / len(vectors)
        for feature in space.features
    }
    return centroid, space


def _artist_affinities(session: Session, playlist: Playlist) -> dict[str, float]:
    """candidate-artist name (casefolded) -> strongest edge from a playlist artist."""
    member_tracks = session.exec(
        select(Track)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
        .where(PlaylistTrack.playlist_id == playlist.id)
    ).all()
    member_artist_ids: set[int] = set()
    member_names = {
        str(credit.get("name", "")).casefold()
        for track in member_tracks
        for credit in track.artists
    }
    if member_names:
        rows = session.exec(select(Artist)).all()
        member_artist_ids = {a.id for a in rows if a.name.casefold() in member_names and a.id}
    if not member_artist_ids:
        return {}
    edges = session.exec(
        select(ArtistSimilarity).where(col(ArtistSimilarity.artist_id).in_(member_artist_ids))
    ).all()
    affinities: dict[str, float] = {}
    for edge in edges:
        key = edge.similar_artist_name.casefold()
        affinities[key] = max(affinities.get(key, 0.0), edge.weight)
    return affinities


def _feedback_tallies(session: Session, user: User) -> dict[str, tuple[int, int]]:
    """artist (casefolded) -> (accepts, rejects) across the whole history."""
    rows = session.exec(
        select(SuggestionFeedback).where(SuggestionFeedback.user_id == user.id)
    ).all()
    tallies: dict[str, tuple[int, int]] = {}
    for row in rows:
        accepts, rejects = tallies.get(row.artist.casefold(), (0, 0))
        if row.action == FeedbackAction.accept:
            accepts += 1
        elif row.action == FeedbackAction.reject:
            rejects += 1
        tallies[row.artist.casefold()] = (accepts, rejects)
    return tallies


def _suggestion_counts(session: Session, user: User) -> dict[str, int]:
    """artist (casefolded) -> total candidates ever proposed for this user."""
    rows = session.exec(
        select(DiscoveryCandidate.artist).where(DiscoveryCandidate.user_id == user.id)
    ).all()
    counts: dict[str, int] = {}
    for artist in rows:
        counts[artist.casefold()] = counts.get(artist.casefold(), 0) + 1
    return counts


def build_suggestion_queue(session: Session, user: User, playlist: Playlist) -> list[QueueEntry]:
    """Resolved candidates for the playlist, best fit first."""
    candidates = session.exec(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.playlist_id == playlist.id)
        .where(DiscoveryCandidate.status == CandidateStatus.resolved)
        .order_by(col(DiscoveryCandidate.id))
    ).all()
    if not candidates:
        return []

    centroid, space = _playlist_centroid(session, user, playlist)
    affinities = _artist_affinities(session, playlist)
    tallies = _feedback_tallies(session, user)
    counts = _suggestion_counts(session, user)

    vectors: dict[int, dict[str, float]] = {}
    inputs: list[RankInput] = []
    for candidate in candidates:
        assert candidate.id is not None
        vector = space.transform(candidate.features) if candidate.features else {}
        vectors[candidate.id] = vector
        artist_key = candidate.artist.casefold()
        accepts, rejects = tallies.get(artist_key, (0, 0))
        inputs.append(
            RankInput(
                candidate_id=candidate.id,
                vector=vector,
                affinity=affinities.get(artist_key, 0.0),
                prior_suggestions=max(0, counts.get(artist_key, 1) - 1),
                accepts=accepts,
                rejects=rejects,
            )
        )

    by_id = {c.id: c for c in candidates}
    entries: list[QueueEntry] = []
    for ranked in rank(inputs, centroid):
        candidate = by_id[ranked.candidate_id]
        vector = vectors[ranked.candidate_id]
        fingerprint = [
            {
                "feature": feature,
                "candidate": round(vector.get(feature, 0.5), 4),
                "playlist": round(centroid.get(feature, 0.5), 4),
            }
            for feature in FINGERPRINT_FEATURES
        ]
        entries.append(
            QueueEntry(candidate=candidate, breakdown=ranked.breakdown, fingerprint=fingerprint)
        )
    return entries


def record_feedback(
    session: Session, user: User, candidate: DiscoveryCandidate, action: FeedbackAction
) -> SuggestionFeedback:
    """Store the decision and move the candidate's lifecycle accordingly.

    Accept status is set here; the actual playlist write happens in
    accept_candidate (which calls this).
    """
    feedback = SuggestionFeedback(
        user_id=user.id,
        candidate_id=candidate.id,
        playlist_id=candidate.playlist_id,
        artist=candidate.artist,
        action=action,
    )
    session.add(feedback)
    if action == FeedbackAction.reject:
        candidate.status = CandidateStatus.rejected
        session.add(candidate)
    elif action == FeedbackAction.accept:
        candidate.status = CandidateStatus.accepted
        session.add(candidate)
    session.commit()
    session.refresh(feedback)
    return feedback


def _track_for_candidate(session: Session, candidate: DiscoveryCandidate) -> Track:
    """The catalog row an accepted candidate adds — created when unknown."""
    track = session.exec(select(Track).where(Track.spotify_id == candidate.spotify_id)).first()
    if track is not None:
        return track
    track = Track(
        spotify_id=candidate.spotify_id or "",
        isrc=candidate.isrc,
        name=candidate.title,
        # The artist's Spotify ID is unknown until a sync sees this track;
        # sync upserts by track id and completes the credit later.
        artists=[{"spotify_id": None, "name": candidate.artist}],
        album_name=candidate.album_name,
        duration_ms=candidate.duration_ms,
    )
    session.add(track)
    session.flush()
    return track


async def accept_candidate(
    session: Session,
    user: User,
    candidate: DiscoveryCandidate,
    writer: SpotifyWriter,
) -> tuple[SuggestionFeedback, int]:
    """Accept: journal-first playlist add via the standard write path.

    Returns (feedback row, journal id) — the journal id drives the undo toast.
    """
    track = _track_for_candidate(session, candidate)
    service = MutationService(session=session, writer=writer, user=user)
    assert track.id is not None
    journal = await service.add_tracks(candidate.playlist_id, [track.id])
    feedback = record_feedback(session, user, candidate, FeedbackAction.accept)
    assert journal.id is not None
    return feedback, journal.id
