"""Full op cycle over MySQL against a mock Spotify HTTP server.

The real SpotifyClient (bearer auth, chunking, JSON shapes) talks to a
stateful httpx.MockTransport implementation of the playlist endpoints, so the
whole production write path — endpoint → MutationService → planner →
SpotifyClient → HTTP — runs end to end, with the real migrated schema.
"""

import json
import re
from contextlib import asynccontextmanager

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

from crate.app import create_app
from crate.db import get_session
from crate.deps import get_current_user, get_writer_factory
from crate.model.orm import (
    MutationJournal,
    OpPreview,
    Playlist,
    PlaylistTrack,
    SyncEvent,
    Track,
    User,
    utcnow,
)
from crate.services.mutations.writer import ClientWriter
from crate.services.spotify.client import SpotifyClient
from crate.settings import get_settings
from tests.mutation_fakes import spotify_reorder
from tests.test_migrations_integration import alembic_config, drop_everything

pytestmark = pytest.mark.integration


class MockSpotifyServer:
    """Stateful handler for httpx.MockTransport implementing the write API."""

    def __init__(self) -> None:
        self.playlists: dict[str, dict] = {}
        self._snapshot_counter = 0
        self._playlist_counter = 0

    def seed(self, spotify_id: str, name: str, uris: list[str]) -> None:
        self.playlists[spotify_id] = {"name": name, "description": None, "uris": list(uris)}

    def _snapshot(self, spotify_id: str) -> str:
        self._snapshot_counter += 1
        return f"msnap-{self._snapshot_counter}"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}

        if path == "/v1/me":
            return httpx.Response(200, json={"id": "jt", "display_name": "JT"})

        match = re.fullmatch(r"/v1/users/([^/]+)/playlists", path)
        if match and request.method == "POST":
            self._playlist_counter += 1
            spotify_id = f"mock-pl-{self._playlist_counter}"
            self.playlists[spotify_id] = {
                "name": body["name"],
                "description": body.get("description"),
                "uris": [],
            }
            return httpx.Response(
                201, json={"id": spotify_id, "snapshot_id": self._snapshot(spotify_id)}
            )

        match = re.fullmatch(r"/v1/playlists/([^/]+)/tracks", path)
        if match:
            state = self.playlists[match.group(1)]
            if request.method == "GET":
                items = [{"track": {"uri": uri, "name": uri}} for uri in state["uris"]]
                return httpx.Response(200, json={"items": items, "next": None})
            if request.method == "POST":
                position = body.get("position")
                if position is None:
                    state["uris"].extend(body["uris"])
                else:
                    state["uris"][position:position] = body["uris"]
                return httpx.Response(201, json={"snapshot_id": self._snapshot(match.group(1))})
            if request.method == "DELETE":
                drop = {t["uri"] for t in body["tracks"]}
                state["uris"] = [u for u in state["uris"] if u not in drop]
                return httpx.Response(200, json={"snapshot_id": self._snapshot(match.group(1))})
            if request.method == "PUT":
                state["uris"] = spotify_reorder(
                    state["uris"],
                    body["range_start"],
                    body["insert_before"],
                    body.get("range_length", 1),
                )
                return httpx.Response(200, json={"snapshot_id": self._snapshot(match.group(1))})

        match = re.fullmatch(r"/v1/playlists/([^/]+)/followers", path)
        if match and request.method == "DELETE":
            self.playlists.pop(match.group(1), None)
            return httpx.Response(200, text="")

        match = re.fullmatch(r"/v1/playlists/([^/]+)", path)
        if match and request.method == "PUT":
            state = self.playlists[match.group(1)]
            state["name"] = body.get("name", state["name"])
            state["description"] = body.get("description", state["description"])
            return httpx.Response(200, text="")

        return httpx.Response(404, json={"error": {"message": f"unhandled {path}"}})


@pytest.fixture(scope="module")
def migrated_engine():
    drop_everything()
    command.upgrade(alembic_config(), "head")
    engine = create_engine(get_settings().database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine):
    with Session(migrated_engine) as session:
        # Isolate from other module runs: everything that references playlists.
        for model in (MutationJournal, OpPreview, SyncEvent, PlaylistTrack, Playlist):
            for row in session.exec(select(model)).all():
                session.delete(row)
        session.commit()
        yield session


@pytest.fixture
def user(session: Session) -> User:
    row = session.exec(select(User).where(User.clerk_user_id == "mut-int-user")).first()
    if row is None:
        row = User(clerk_user_id="mut-int-user", spotify_user_id="jt")
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@pytest.fixture
def server() -> MockSpotifyServer:
    return MockSpotifyServer()


@pytest.fixture
def client(session: Session, user: User, server: MockSpotifyServer) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user

    @asynccontextmanager
    async def writer_factory(_session: Session, _user: User):
        spotify = SpotifyClient(
            client_id="test",
            access_token="tok",
            refresh_token="refresh",
            transport=httpx.MockTransport(server),
        )
        try:
            yield ClientWriter(spotify)
        finally:
            await spotify.aclose()

    app.dependency_overrides[get_writer_factory] = lambda: writer_factory
    return TestClient(app)


def seed(
    session: Session, user: User, server: MockSpotifyServer, playlists: dict[str, list[str]]
) -> dict[str, Playlist]:
    result: dict[str, Playlist] = {}
    for name, sids in playlists.items():
        spotify_id = f"sp-{name}"
        playlist = Playlist(user_id=user.id, spotify_id=spotify_id, name=name, is_owned=True)
        session.add(playlist)
        session.flush()
        for position, sid in enumerate(sids):
            track = session.exec(select(Track).where(Track.spotify_id == sid)).first()
            if track is None:
                track = Track(
                    spotify_id=sid,
                    name=f"Track {sid}",
                    isrc=f"II-{sid}",
                    artists=[{"spotify_id": f"a-{sid}", "name": f"Artist {sid}"}],
                )
                session.add(track)
                session.flush()
            session.add(
                PlaylistTrack(
                    user_id=user.id,
                    playlist_id=playlist.id,
                    track_id=track.id,
                    position=position,
                    added_at=utcnow(),
                )
            )
        server.seed(spotify_id, name, [f"spotify:track:{sid}" for sid in sids])
        result[name] = playlist
    session.commit()
    return result


def db_order(session: Session, playlist_id: int) -> list[str]:
    rows = session.exec(
        select(PlaylistTrack, Track)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .where(PlaylistTrack.track_id == Track.id)
        .order_by(PlaylistTrack.position)
    ).all()
    return [track.spotify_id for _, track in rows]


def test_full_single_op_cycle(
    client: TestClient, session: Session, user: User, server: MockSpotifyServer
) -> None:
    lib = seed(session, user, server, {"Gym": ["ta", "tb"], "Pool": ["tc"]})
    tc = session.exec(select(Track).where(Track.spotify_id == "tc")).one()

    # add → remote + local agree
    added = client.post(f"/v1/playlists/{lib['Gym'].id}/tracks", json={"track_ids": [tc.id]})
    assert added.status_code == 200
    assert server.playlists["sp-Gym"]["uris"] == [
        "spotify:track:ta",
        "spotify:track:tb",
        "spotify:track:tc",
    ]
    assert db_order(session, lib["Gym"].id) == ["ta", "tb", "tc"]

    # snapshot_id advanced from the mock server's write
    session.refresh(lib["Gym"])
    assert lib["Gym"].snapshot_id and lib["Gym"].snapshot_id.startswith("msnap-")

    # undo → both sides restored
    undo = client.post(f"/v1/journal/{added.json()['journal_id']}/undo")
    assert undo.status_code == 200
    assert server.playlists["sp-Gym"]["uris"] == ["spotify:track:ta", "spotify:track:tb"]
    assert db_order(session, lib["Gym"].id) == ["ta", "tb"]


def test_full_bulk_cycle_preview_apply_undo(
    client: TestClient, session: Session, user: User, server: MockSpotifyServer
) -> None:
    lib = seed(session, user, server, {"A": ["ta", "tb"], "B": ["tb", "tc"]})

    preview = client.post(
        "/v1/ops/preview",
        json={
            "operation": "union",
            "source_ids": [lib["A"].id, lib["B"].id],
            "new_playlist_name": "Everything",
        },
    ).json()
    assert preview["manifest"]["summary"] == {"adds": 3, "removes": 0, "playlists": 1}

    applied = client.post("/v1/ops/apply", json={"preview_id": preview["preview_id"]})
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"

    created = session.exec(select(Playlist).where(Playlist.name == "Everything")).one()
    assert db_order(session, created.id) == ["ta", "tb", "tc"]
    assert server.playlists[created.spotify_id]["uris"] == [
        "spotify:track:ta",
        "spotify:track:tb",
        "spotify:track:tc",
    ]

    # journal shows the bulk entry; undo unwinds the created playlist
    journal = client.get("/v1/journal").json()
    assert journal["items"][0]["op_type"] == "bulk"
    undo = client.post(f"/v1/journal/{journal['items'][0]['id']}/undo")
    assert undo.status_code == 200
    session.refresh(created)
    assert created.is_deleted
    assert created.spotify_id not in server.playlists  # unfollowed on Spotify


def test_reorder_and_rename_cycle(
    client: TestClient, session: Session, user: User, server: MockSpotifyServer
) -> None:
    lib = seed(session, user, server, {"Flow": ["ta", "tb", "tc"]})
    ids = {
        sid: session.exec(select(Track).where(Track.spotify_id == sid)).one().id
        for sid in ["ta", "tb", "tc"]
    }

    reorder = client.put(
        f"/v1/playlists/{lib['Flow'].id}/order",
        json={"order": [ids["tc"], ids["ta"], ids["tb"]]},
    )
    assert reorder.status_code == 200
    assert db_order(session, lib["Flow"].id) == ["tc", "ta", "tb"]
    assert server.playlists["sp-Flow"]["uris"] == [
        "spotify:track:tc",
        "spotify:track:ta",
        "spotify:track:tb",
    ]

    renamed = client.patch(f"/v1/playlists/{lib['Flow'].id}", json={"name": "Flow v2"})
    assert renamed.status_code == 200
    assert server.playlists["sp-Flow"]["name"] == "Flow v2"

    # undo both, newest first
    entries = client.get("/v1/journal").json()["items"]
    for entry in entries:
        assert client.post(f"/v1/journal/{entry['id']}/undo").status_code == 200
    assert db_order(session, lib["Flow"].id) == ["ta", "tb", "tc"]
    assert server.playlists["sp-Flow"]["name"] == "Flow"
    assert server.playlists["sp-Flow"]["uris"] == [
        "spotify:track:ta",
        "spotify:track:tb",
        "spotify:track:tc",
    ]
