"""Radio endpoint contracts: creation, session reads, per-item feedback."""

import random
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_radio_builder, get_writer_factory
from crate.model.enums import (
    CandidateSource,
    CandidateStatus,
    FeedbackAction,
)
from crate.model.orm import (
    DiscoveryCandidate,
    MutationJournal,
    Playlist,
    SuggestionFeedback,
    User,
)
from crate.services.radio.service import create_radio_session
from tests.discovery_fakes import seed_playlist
from tests.mutation_fakes import FakeSpotify

pytestmark = pytest.mark.unit


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify()


@pytest.fixture
def client(session: Session, user: User, fake: FakeSpotify) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user

    @asynccontextmanager
    async def fake_writer(_session: Session, _user: User):
        yield fake

    app.dependency_overrides[get_writer_factory] = lambda: fake_writer

    async def offline_builder(
        _session: Session,
        _user: User,
        playlist_id: int | None,
        track_ids: list[int] | None,
        genre_name: str | None,
        length: int,
        discovery_ratio: float,
    ):
        return await create_radio_session(
            _session,
            _user,
            playlist_id=playlist_id,
            track_ids=track_ids,
            genre_name=genre_name,
            length=length,
            discovery_ratio=discovery_ratio,
            previews=None,
            rng=random.Random(0),
        )

    app.dependency_overrides[get_radio_builder] = lambda: offline_builder
    return TestClient(app)


@pytest.fixture
def gym(session: Session, user: User, fake: FakeSpotify) -> Playlist:
    playlist = seed_playlist(
        session,
        user,
        "Gym",
        [(f"g{i}", f"Song {i}", f"Artist {i}") for i in range(4)],
        features={f"g{i}": {"energy": 0.5 + i * 0.05, "tempo": 128.0} for i in range(4)},
    )
    fake.seed(playlist.spotify_id, playlist.name, [f"spotify:track:g{i}" for i in range(4)])
    session.commit()
    return playlist


def seed_candidate(
    session: Session, user: User, playlist: Playlist, title: str
) -> DiscoveryCandidate:
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        status=CandidateStatus.resolved,
        title=title,
        artist=f"{title} Artist",
        dedup_key=f"{title.casefold()}|k",
        spotify_id=f"cand-{title}",
        preview_url="https://cdn.example/c.mp3",
        features={"energy": 0.6, "tempo": 126.0},
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def start_radio(client: TestClient, playlist_id: int, **overrides) -> dict:
    body = {"playlist_id": playlist_id, "length": 10, "discovery_ratio": 0.2, **overrides}
    response = client.post("/v1/radio", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- creation -------------------------------------------------------------------


def test_create_playlist_radio_returns_ordered_session(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    seed_candidate(session, user, gym, "candA")

    body = start_radio(client, gym.id)

    assert body["seed_kind"] == "playlist"
    assert body["seed_playlist_id"] == gym.id
    assert body["label"] == "Gym"
    assert [item["position"] for item in body["items"]] == list(range(5))
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"library", "discovery"}
    discovery = [item for item in body["items"] if item["kind"] == "discovery"]
    assert discovery[0]["preview_url"] == "https://cdn.example/c.mp3"
    assert body["summary"] == {"kept": 0, "skipped": 0, "added": 0, "pending": 5}
    assert body["_links"]["self"]["href"] == f"/v1/radio/{body['id']}"
    feedback_href = discovery[0]["_links"]["feedback"]["href"]
    assert feedback_href == f"/v1/radio/{body['id']}/items/{discovery[0]['id']}/feedback"


def test_create_radio_requires_exactly_one_seed(client: TestClient, gym: Playlist) -> None:
    none_given = client.post("/v1/radio", json={})
    assert none_given.status_code == 400
    assert none_given.json()["error_code"] == "RADIO_SEED_INVALID"

    two_given = client.post("/v1/radio", json={"playlist_id": gym.id, "genre_seed": "trip hop"})
    assert two_given.status_code == 400
    assert two_given.json()["error_code"] == "RADIO_SEED_INVALID"


def test_create_radio_unknown_playlist_404s(client: TestClient) -> None:
    response = client.post("/v1/radio", json={"playlist_id": 999})
    assert response.status_code == 404
    assert response.json()["error_code"] == "PLAYLIST_NOT_FOUND"


def test_get_radio_returns_session_and_404s_for_unknown(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    created = start_radio(client, gym.id)

    fetched = client.get(f"/v1/radio/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["items"] == created["items"]

    assert client.get("/v1/radio/999").status_code == 404


# --- feedback -------------------------------------------------------------------


def item_of_kind(body: dict, kind: str) -> dict:
    return next(item for item in body["items"] if item["kind"] == kind)


def test_skip_library_item_records_no_suggestion_feedback(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    body = start_radio(client, gym.id)
    item = item_of_kind(body, "library")

    response = client.post(
        f"/v1/radio/{body['id']}/items/{item['id']}/feedback", json={"action": "skip"}
    )
    assert response.status_code == 200
    assert response.json()["feedback"] == "skipped"
    assert session.exec(select(SuggestionFeedback)).all() == []


def test_skip_discovery_item_feeds_suggestion_feedback(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = seed_candidate(session, user, gym, "candA")
    body = start_radio(client, gym.id)
    item = item_of_kind(body, "discovery")

    response = client.post(
        f"/v1/radio/{body['id']}/items/{item['id']}/feedback", json={"action": "skip"}
    )
    assert response.status_code == 200
    rows = session.exec(select(SuggestionFeedback)).all()
    assert [(row.candidate_id, row.action) for row in rows] == [(candidate.id, FeedbackAction.skip)]
    session.refresh(candidate)
    assert candidate.status == CandidateStatus.resolved  # a radio skip never bars a track


def test_keep_discovery_item_without_add_signals_the_ranker(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    candidate = seed_candidate(session, user, gym, "candA")
    body = start_radio(client, gym.id)
    item = item_of_kind(body, "discovery")

    response = client.post(
        f"/v1/radio/{body['id']}/items/{item['id']}/feedback", json={"action": "keep"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["feedback"] == "kept"
    assert payload["journal_id"] is None
    rows = session.exec(select(SuggestionFeedback)).all()
    assert [(row.candidate_id, row.action) for row in rows] == [
        (candidate.id, FeedbackAction.accept)
    ]
    session.refresh(candidate)
    # Signal only: the candidate stays reviewable in the deck.
    assert candidate.status == CandidateStatus.resolved


def test_keep_discovery_item_with_add_journals_the_write(
    client: TestClient, session: Session, user: User, gym: Playlist, fake: FakeSpotify
) -> None:
    candidate = seed_candidate(session, user, gym, "candA")
    body = start_radio(client, gym.id)
    item = item_of_kind(body, "discovery")

    response = client.post(
        f"/v1/radio/{body['id']}/items/{item['id']}/feedback",
        json={"action": "keep", "add_to_playlist_id": gym.id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["feedback"] == "kept"
    assert payload["journal_id"] is not None
    assert payload["_links"]["undo"]["href"] == f"/v1/journal/{payload['journal_id']}/undo"

    journal = session.get(MutationJournal, payload["journal_id"])
    assert journal is not None
    session.refresh(candidate)
    assert candidate.status == CandidateStatus.accepted
    assert f"spotify:track:{candidate.spotify_id}" in fake.listing(gym.spotify_id)

    # The session summary now counts the add.
    summary = client.get(f"/v1/radio/{body['id']}").json()["summary"]
    assert summary["kept"] == 1
    assert summary["added"] == 1


def test_feedback_is_write_once(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    body = start_radio(client, gym.id)
    item = item_of_kind(body, "library")
    url = f"/v1/radio/{body['id']}/items/{item['id']}/feedback"

    assert client.post(url, json={"action": "keep"}).status_code == 200
    second = client.post(url, json={"action": "skip"})
    assert second.status_code == 409
    assert second.json()["error_code"] == "RADIO_ITEM_ALREADY_REVIEWED"


def test_add_to_playlist_rejected_for_library_items(
    client: TestClient, session: Session, user: User, gym: Playlist
) -> None:
    body = start_radio(client, gym.id)
    item = item_of_kind(body, "library")

    response = client.post(
        f"/v1/radio/{body['id']}/items/{item['id']}/feedback",
        json={"action": "keep", "add_to_playlist_id": gym.id},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "RADIO_ADD_NOT_CANDIDATE"
