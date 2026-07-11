"""Discovery endpoint contracts: HAL, RFC 7807, and the journaled accept path."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_discovery_runner, get_writer_factory
from crate.model.enums import CandidateSource, CandidateStatus, FeedbackAction
from crate.model.orm import (
    DiscoveryCandidate,
    MutationJournal,
    Playlist,
    PlaylistTrack,
    SuggestionFeedback,
    Track,
    User,
)
from crate.services.discovery.generation import dedup_key
from crate.services.discovery.wiring import DiscoveryReport
from tests.discovery_fakes import seed_playlist
from tests.mutation_fakes import FakeSpotify

pytestmark = pytest.mark.unit

HOT = {"energy": 0.9, "valence": 0.6, "danceability": 0.85, "acousticness": 0.05}
COLD = {"energy": 0.2, "valence": 0.3, "danceability": 0.3, "acousticness": 0.9}


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


@pytest.fixture
def run_calls() -> list[tuple[int | None, int]]:
    return []


@pytest.fixture
def client(
    session: Session, user: User, fake: FakeSpotify, run_calls: list[tuple[int | None, int]]
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user

    @asynccontextmanager
    async def fake_writer(_session: Session, _user: User):
        yield fake

    app.dependency_overrides[get_writer_factory] = lambda: fake_writer

    async def fake_runner(
        _session: Session, _user: User, playlist_id: int | None, limit: int
    ) -> DiscoveryReport:
        run_calls.append((playlist_id, limit))
        return DiscoveryReport(playlists_processed=1, generated_reccobeats=3, resolved=3)

    app.dependency_overrides[get_discovery_runner] = lambda: fake_runner
    return TestClient(app)


@pytest.fixture
def gym(session: Session, user: User, fake: FakeSpotify) -> Playlist:
    playlist = seed_playlist(
        session,
        user,
        "Gym",
        [("t-a", "Track A", "KREAM"), ("t-b", "Track B", "Skrillex")],
        features={"t-a": HOT, "t-b": HOT},
    )
    # Mirror membership into the fake Spotify server so writes reconcile.
    fake.seed(playlist.spotify_id, "Gym", ["spotify:track:t-a", "spotify:track:t-b"])
    return playlist


def add_candidate(
    session: Session,
    user: User,
    playlist: Playlist,
    title: str,
    artist: str,
    features: dict[str, float] | None = HOT,
    status: CandidateStatus = CandidateStatus.resolved,
    preview: str | None = "https://cdn.example/p.mp3",
) -> DiscoveryCandidate:
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        status=status,
        title=title,
        artist=artist,
        dedup_key=dedup_key(title, artist),
        spotify_id=f"sp-{title.lower().replace(' ', '-')}",
        isrc=None,
        album_name=f"{title} LP",
        duration_ms=200_000,
        preview_url=preview,
        features=features,
        seed_artist="KREAM",
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


# ---------------------------------------------------------------- suggestions


def test_suggestions_ranked_with_breakdown_and_links(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    close = add_candidate(session, user, gym, "Close", "Cassian", HOT)
    far = add_candidate(session, user, gym, "Far", "Iron & Wine", COLD)

    response = client.get(f"/v1/playlists/{gym.id}/suggestions")

    assert response.status_code == 200
    body = response.json()
    assert body["playlist_name"] == "Gym"
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [close.id, far.id]
    first = body["items"][0]
    assert first["fit"] == first["breakdown"]["fit"]
    assert {"proximity", "affinity", "novelty", "feedback", "fit"} <= set(first["breakdown"])
    assert {p["feature"] for p in first["fingerprint"]} == {
        "energy",
        "valence",
        "acousticness",
    }
    assert first["preview_url"] == "https://cdn.example/p.mp3"
    assert first["_links"]["feedback"]["href"] == f"/v1/suggestions/{close.id}/feedback"
    assert first["_links"]["spotify"]["href"].startswith("https://open.spotify.com/track/")
    assert body["_links"]["run"]["href"] == "/v1/discovery/run"


def test_suggestions_unknown_playlist_404s(client: TestClient) -> None:
    response = client.get("/v1/playlists/999/suggestions")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "PLAYLIST_NOT_FOUND"


def test_suggestions_hide_fake_spotify_links(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(session, user, gym, "Fake", "Someone")
    candidate.spotify_id = "fake-abc123"
    session.add(candidate)
    session.commit()

    body = client.get(f"/v1/playlists/{gym.id}/suggestions").json()
    assert "spotify" not in body["items"][0]["_links"]


# ------------------------------------------------------------------- feedback


def test_accept_adds_track_via_journaled_write_path(
    client: TestClient, session: Session, user: User, gym: Playlist, fake: FakeSpotify
) -> None:
    candidate = add_candidate(session, user, gym, "Magical", "Cassian")

    response = client.post(f"/v1/suggestions/{candidate.id}/feedback", json={"action": "accept"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["journal_id"] is not None
    assert body["_links"]["undo"]["href"] == f"/v1/journal/{body['journal_id']}/undo"

    journal = session.get(MutationJournal, body["journal_id"])
    assert journal is not None and journal.status.value == "applied"

    # The track landed in the playlist (position 2, appended).
    track = session.exec(select(Track).where(Track.spotify_id == "sp-magical")).one()
    membership = session.exec(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == gym.id)
        .where(PlaylistTrack.track_id == track.id)
    ).one()
    assert membership.position == 2
    # And on the (fake) Spotify side.
    assert "spotify:track:sp-magical" in fake.listing(gym.spotify_id)


def test_accept_then_undo_restores_membership(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(session, user, gym, "Magical", "Cassian")
    journal_id = client.post(
        f"/v1/suggestions/{candidate.id}/feedback", json={"action": "accept"}
    ).json()["journal_id"]

    undo = client.post(f"/v1/journal/{journal_id}/undo")
    assert undo.status_code == 200

    track = session.exec(select(Track).where(Track.spotify_id == "sp-magical")).one()
    assert (
        session.exec(
            select(PlaylistTrack)
            .where(PlaylistTrack.playlist_id == gym.id)
            .where(PlaylistTrack.track_id == track.id)
        ).first()
        is None
    )


def test_reject_removes_from_queue(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(session, user, gym, "Nope", "Cassian")

    response = client.post(f"/v1/suggestions/{candidate.id}/feedback", json={"action": "reject"})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["journal_id"] is None
    assert client.get(f"/v1/playlists/{gym.id}/suggestions").json()["total"] == 0


def test_skip_records_but_keeps_candidate(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(session, user, gym, "Later", "Cassian")

    response = client.post(f"/v1/suggestions/{candidate.id}/feedback", json={"action": "skip"})

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    feedback = session.exec(
        select(SuggestionFeedback).where(SuggestionFeedback.candidate_id == candidate.id)
    ).one()
    assert feedback.action == FeedbackAction.skip
    assert client.get(f"/v1/playlists/{gym.id}/suggestions").json()["total"] == 1


def test_feedback_unknown_candidate_404s(client: TestClient) -> None:
    response = client.post("/v1/suggestions/999/feedback", json={"action": "accept"})
    assert response.status_code == 404
    assert response.json()["error_code"] == "SUGGESTION_NOT_FOUND"


def test_feedback_on_reviewed_candidate_409s(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(
        session, user, gym, "Done", "Cassian", status=CandidateStatus.rejected
    )
    response = client.post(f"/v1/suggestions/{candidate.id}/feedback", json={"action": "accept"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "SUGGESTION_NOT_REVIEWABLE"


def test_feedback_rejects_unknown_action(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = add_candidate(session, user, gym, "Odd", "Cassian")
    response = client.post(f"/v1/suggestions/{candidate.id}/feedback", json={"action": "maybe"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


# -------------------------------------------------------------- discovery run


def test_discovery_run_invokes_runner_with_scope(
    client: TestClient,
    gym: Playlist,
    run_calls: list[tuple[int | None, int]],
) -> None:
    response = client.post("/v1/discovery/run", json={"playlist_id": gym.id, "limit": 25})

    assert response.status_code == 200
    body = response.json()
    assert body["playlists_processed"] == 1
    assert body["generated_reccobeats"] == 3
    assert body["_links"]["self"]["href"] == "/v1/discovery/run"
    assert run_calls == [(gym.id, 25)]


def test_discovery_run_defaults_to_all_playlists(
    client: TestClient, run_calls: list[tuple[int | None, int]]
) -> None:
    response = client.post("/v1/discovery/run", json={})
    assert response.status_code == 200
    assert run_calls == [(None, 50)]


def test_discovery_run_unknown_playlist_404s(client: TestClient) -> None:
    response = client.post("/v1/discovery/run", json={"playlist_id": 999})
    assert response.status_code == 404
