"""Field-complete ORM round-trip against the migrated MySQL schema.

Every persisted field of every model is written, reloaded in a fresh session,
and asserted for value AND runtime type — silent coercion (str-ified ints,
truncated microseconds, enum→str decay) fails loudly here.
"""

from datetime import datetime

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine
from sqlmodel import Session

from crate.model.enums import (
    CredentialStatus,
    MutationOpType,
    MutationStatus,
    PlaylistSyncStatus,
    SyncEventSource,
    SyncEventType,
)
from crate.model.orm import (
    Artist,
    MutationJournal,
    Playlist,
    PlaylistTrack,
    SpotifyCredential,
    SyncEvent,
    Track,
    User,
)
from crate.settings import get_settings
from tests.test_migrations_integration import alembic_config, drop_everything

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def migrated_engine():
    drop_everything()
    command.upgrade(alembic_config(), "head")
    engine = create_engine(get_settings().database_url)
    yield engine
    engine.dispose()


def persist_and_reload(engine: Engine, instance):
    model_cls = type(instance)
    with Session(engine) as session:
        session.add(instance)
        session.commit()
        pk = instance.id
    with Session(engine) as session:  # fresh session — guaranteed DB read
        return session.get(model_cls, pk)


def assert_timestamps(row) -> None:
    assert isinstance(row.created_at, datetime)
    assert isinstance(row.updated_at, datetime)
    assert row.created_at.tzinfo is None  # naive UTC convention


def make_user(engine: Engine, suffix: str) -> User:
    return persist_and_reload(
        engine, User(clerk_user_id=f"clerk-{suffix}", spotify_user_id=f"spotify-{suffix}")
    )


def test_user_round_trip(migrated_engine: Engine) -> None:
    row = make_user(migrated_engine, "rt-user")
    assert isinstance(row.id, int)
    assert row.clerk_user_id == "clerk-rt-user"
    assert row.spotify_user_id == "spotify-rt-user"
    assert_timestamps(row)


def test_spotify_credential_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-cred")
    expires = datetime(2026, 7, 11, 12, 30, 45, 123456)
    row = persist_and_reload(
        migrated_engine,
        SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted="gAAAAA-refresh-ciphertext",
            access_token_encrypted="gAAAAA-access-ciphertext",
            access_token_expires_at=expires,
            scope="playlist-read-private streaming",
            status=CredentialStatus.needs_reauth,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int) and row.user_id == user.id
    assert row.refresh_token_encrypted == "gAAAAA-refresh-ciphertext"
    assert row.access_token_encrypted == "gAAAAA-access-ciphertext"
    assert row.access_token_expires_at == expires  # microseconds must survive
    assert isinstance(row.access_token_expires_at, datetime)
    assert row.scope == "playlist-read-private streaming"
    assert row.status == CredentialStatus.needs_reauth
    assert isinstance(row.status, CredentialStatus)
    assert_timestamps(row)


def test_playlist_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-pl")
    synced_at = datetime(2026, 7, 10, 3, 0, 0, 654321)
    row = persist_and_reload(
        migrated_engine,
        Playlist(
            user_id=user.id,
            spotify_id="3cEYpjA9oz9GiPac4AsH4n",
            name="night drives",
            description="Late-night deep cuts",
            snapshot_id="MTgsZWFmMWU0OGVjNzVjZmVh",
            is_owned=False,
            is_deleted=True,
            status=PlaylistSyncStatus.error,
            last_synced_at=synced_at,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int)
    assert row.spotify_id == "3cEYpjA9oz9GiPac4AsH4n"
    assert row.name == "night drives"
    assert row.description == "Late-night deep cuts"
    assert row.snapshot_id == "MTgsZWFmMWU0OGVjNzVjZmVh"
    assert row.is_owned is False
    assert row.is_deleted is True
    assert row.status == PlaylistSyncStatus.error
    assert isinstance(row.status, PlaylistSyncStatus)
    assert row.last_synced_at == synced_at
    assert isinstance(row.last_synced_at, datetime)
    assert_timestamps(row)


def test_track_round_trip(migrated_engine: Engine) -> None:
    artists = [
        {"spotify_id": "4Z8W4fKeB5YxbusRsdQVPb", "name": "Night Artist"},
        {"spotify_id": None, "name": "Local Collaborator"},
    ]
    row = persist_and_reload(
        migrated_engine,
        Track(
            spotify_id="6UelLqGlWMcVH1E5c4H7lY",
            isrc="GBAYE1900123",
            name="Headlights",
            artists=artists,
            album_spotify_id="2up3OPMp9Tb4dAKM2erWXQ",
            album_name="Night Bus",
            duration_ms=214693,
        ),
    )
    assert isinstance(row.id, int)
    assert row.spotify_id == "6UelLqGlWMcVH1E5c4H7lY"
    assert row.isrc == "GBAYE1900123"
    assert row.name == "Headlights"
    assert row.artists == artists  # JSON list order + null values preserved
    assert row.album_spotify_id == "2up3OPMp9Tb4dAKM2erWXQ"
    assert row.album_name == "Night Bus"
    assert row.duration_ms == 214693
    assert isinstance(row.duration_ms, int)
    assert_timestamps(row)


def test_artist_round_trip(migrated_engine: Engine) -> None:
    row = persist_and_reload(
        migrated_engine,
        Artist(
            spotify_id="4Z8W4fKeB5YxbusRsdQVPb",
            name="Night Artist",
            mbid="b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
        ),
    )
    assert isinstance(row.id, int)
    assert row.spotify_id == "4Z8W4fKeB5YxbusRsdQVPb"
    assert row.name == "Night Artist"
    assert row.mbid == "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d"
    assert_timestamps(row)


def test_playlist_track_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-pt")
    playlist = persist_and_reload(
        migrated_engine, Playlist(user_id=user.id, spotify_id="pl-rt-pt", name="rt")
    )
    track = persist_and_reload(
        migrated_engine, Track(spotify_id="tr-rt-pt", name="rt track", artists=[])
    )
    added = datetime(2025, 11, 2, 21, 14, 5, 42)
    row = persist_and_reload(
        migrated_engine,
        PlaylistTrack(
            user_id=user.id,
            playlist_id=playlist.id,
            track_id=track.id,
            position=7,
            added_at=added,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int)
    assert isinstance(row.playlist_id, int) and row.playlist_id == playlist.id
    assert isinstance(row.track_id, int) and row.track_id == track.id
    assert row.position == 7
    assert isinstance(row.position, int)
    assert row.added_at == added
    assert isinstance(row.added_at, datetime)
    assert_timestamps(row)


def test_sync_event_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-ev")
    playlist = persist_and_reload(
        migrated_engine, Playlist(user_id=user.id, spotify_id="pl-rt-ev", name="rt")
    )
    track = persist_and_reload(
        migrated_engine, Track(spotify_id="tr-rt-ev", name="rt track", artists=[])
    )
    observed = datetime(2026, 7, 11, 4, 44, 44, 444444)
    detail = {"from": "old name", "to": "new name", "count": 3}
    row = persist_and_reload(
        migrated_engine,
        SyncEvent(
            user_id=user.id,
            playlist_id=playlist.id,
            track_id=track.id,
            event_type=SyncEventType.playlist_renamed,
            source=SyncEventSource.crate,
            observed_at=observed,
            detail=detail,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int)
    assert isinstance(row.playlist_id, int)
    assert isinstance(row.track_id, int)
    assert row.event_type == SyncEventType.playlist_renamed
    assert isinstance(row.event_type, SyncEventType)
    assert row.source == SyncEventSource.crate
    assert isinstance(row.source, SyncEventSource)
    assert row.observed_at == observed
    assert isinstance(row.observed_at, datetime)
    assert row.detail == detail
    assert isinstance(row.detail["count"], int)
    assert_timestamps(row)


def test_mutation_journal_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-mj")
    payload = {"playlist_id": 1, "track_ids": ["a", "b"]}
    inverse = {"playlist_id": 1, "restore_order": ["b", "a"]}
    row = persist_and_reload(
        migrated_engine,
        MutationJournal(
            user_id=user.id,
            op_type=MutationOpType.add_tracks,
            payload=payload,
            inverse_payload=inverse,
            status=MutationStatus.applied,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int)
    assert row.op_type == MutationOpType.add_tracks
    assert isinstance(row.op_type, MutationOpType)
    assert row.payload == payload
    assert row.inverse_payload == inverse
    assert row.status == MutationStatus.applied
    assert isinstance(row.status, MutationStatus)
    assert_timestamps(row)


def test_created_at_microseconds_survive(migrated_engine: Engine) -> None:
    """The DATETIME(6) columns must not truncate sub-second precision."""
    row = persist_and_reload(
        migrated_engine,
        Track(
            spotify_id="tr-rt-micros",
            name="precision",
            artists=[],
            created_at=datetime(2026, 7, 11, 1, 2, 3, 999999),
        ),
    )
    assert row.created_at == datetime(2026, 7, 11, 1, 2, 3, 999999)
