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
    BulkOperation,
    CredentialStatus,
    FeatureSource,
    FeatureStatus,
    MutationOpType,
    MutationStatus,
    PlaylistSyncStatus,
    SimilaritySource,
    SnapshotKind,
    SyncEventSource,
    SyncEventType,
    TagSource,
)
from crate.model.orm import (
    AnalyticsSnapshot,
    ApiResponseCache,
    Artist,
    ArtistGenre,
    ArtistSimilarity,
    ArtistTag,
    FeatureCalibration,
    FreqBlogBudget,
    Genre,
    MutationJournal,
    OpPreview,
    Playlist,
    PlaylistTrack,
    SpotifyCredential,
    SyncEvent,
    Track,
    TrackFeatures,
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
    undone = datetime(2026, 7, 11, 21, 2, 3, 456789)
    row = persist_and_reload(
        migrated_engine,
        MutationJournal(
            user_id=user.id,
            op_type=MutationOpType.add_tracks,
            payload=payload,
            inverse_payload=inverse,
            status=MutationStatus.partial,
            undone_at=undone,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int)
    assert row.op_type == MutationOpType.add_tracks
    assert isinstance(row.op_type, MutationOpType)
    assert row.payload == payload
    assert row.inverse_payload == inverse
    assert row.status == MutationStatus.partial
    assert isinstance(row.status, MutationStatus)
    assert row.undone_at == undone  # microseconds must survive
    assert isinstance(row.undone_at, datetime)
    assert_timestamps(row)


def test_op_preview_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-op")
    params = {"operation": "dedupe", "source_ids": [3], "target_id": None}
    manifest = {
        "entries": [
            {
                "playlist_id": 3,
                "playlist_name": "Chill",
                "new": False,
                "adds": [],
                "removes": [{"position": 2, "track_id": 9, "spotify_id": "t9", "name": "N"}],
            }
        ],
        "summary": {"adds": 0, "removes": 1, "playlists": 1},
    }
    fingerprint = "f" * 64
    row = persist_and_reload(
        migrated_engine,
        OpPreview(
            user_id=user.id,
            operation=BulkOperation.dedupe,
            params=params,
            manifest=manifest,
            fingerprint=fingerprint,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.user_id, int) and row.user_id == user.id
    assert row.operation == BulkOperation.dedupe
    assert isinstance(row.operation, BulkOperation)
    assert row.params == params
    assert row.manifest == manifest
    assert isinstance(row.manifest["summary"]["removes"], int)
    assert row.fingerprint == fingerprint
    assert_timestamps(row)


def test_track_features_round_trip(migrated_engine: Engine) -> None:
    track = persist_and_reload(
        migrated_engine, Track(spotify_id="tr-rt-feat", name="rt", artists=[])
    )
    fetched = datetime(2026, 7, 11, 9, 8, 7, 654321)
    row = persist_and_reload(
        migrated_engine,
        TrackFeatures(
            track_id=track.id,
            energy=0.816,
            valence=0.557,
            danceability=0.548,
            acousticness=0.122,
            instrumentalness=0.0,
            liveness=0.335,
            speechiness=0.0465,
            tempo=95.39,
            key=0,
            mode=1,
            loudness=-4.209,
            status=FeatureStatus.present,
            source=FeatureSource.reccobeats,
            fetched_at=fetched,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.track_id, int) and row.track_id == track.id
    assert row.energy == pytest.approx(0.816)
    assert row.valence == pytest.approx(0.557)
    assert row.danceability == pytest.approx(0.548)
    assert row.acousticness == pytest.approx(0.122)
    assert row.instrumentalness == pytest.approx(0.0)
    assert row.liveness == pytest.approx(0.335)
    assert row.speechiness == pytest.approx(0.0465)
    assert row.tempo == pytest.approx(95.39)
    assert row.key == 0 and isinstance(row.key, int)
    assert row.mode == 1 and isinstance(row.mode, int)
    assert row.loudness == pytest.approx(-4.209)
    assert row.status == FeatureStatus.present
    assert isinstance(row.status, FeatureStatus)
    assert row.source == FeatureSource.reccobeats
    assert isinstance(row.source, FeatureSource)
    assert row.fetched_at == fetched
    assert isinstance(row.fetched_at, datetime)
    assert_timestamps(row)


def test_artist_similarity_round_trip(migrated_engine: Engine) -> None:
    artist = persist_and_reload(migrated_engine, Artist(spotify_id="ar-rt-sim", name="Tycho"))
    linked = persist_and_reload(
        migrated_engine, Artist(spotify_id="ar-rt-sim2", name="Boards of Canada")
    )
    row = persist_and_reload(
        migrated_engine,
        ArtistSimilarity(
            artist_id=artist.id,
            similar_artist_id=linked.id,
            similar_artist_name="Boards of Canada",
            similar_artist_mbid="69158f97-4c07-4c4e-baf8-4e4ab1ed666e",
            weight=0.87,
            source=SimilaritySource.lastfm,
        ),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.artist_id, int) and row.artist_id == artist.id
    assert isinstance(row.similar_artist_id, int) and row.similar_artist_id == linked.id
    assert row.similar_artist_name == "Boards of Canada"
    assert row.similar_artist_mbid == "69158f97-4c07-4c4e-baf8-4e4ab1ed666e"
    assert row.weight == pytest.approx(0.87)
    assert isinstance(row.weight, float)
    assert row.source == SimilaritySource.lastfm
    assert isinstance(row.source, SimilaritySource)
    assert_timestamps(row)


def test_artist_tag_round_trip(migrated_engine: Engine) -> None:
    artist = persist_and_reload(migrated_engine, Artist(spotify_id="ar-rt-tag", name="Tycho"))
    row = persist_and_reload(
        migrated_engine,
        ArtistTag(artist_id=artist.id, tag="electronic", weight=100.0, source=TagSource.lastfm),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.artist_id, int) and row.artist_id == artist.id
    assert row.tag == "electronic"
    assert row.weight == pytest.approx(100.0)
    assert isinstance(row.weight, float)
    assert row.source == TagSource.lastfm
    assert isinstance(row.source, TagSource)
    assert_timestamps(row)


def test_genre_and_artist_genre_round_trip(migrated_engine: Engine) -> None:
    genre = persist_and_reload(migrated_engine, Genre(name="chillwave", enao_rank=147))
    assert isinstance(genre.id, int)
    assert genre.name == "chillwave"
    assert genre.enao_rank == 147
    assert isinstance(genre.enao_rank, int)
    assert_timestamps(genre)

    artist = persist_and_reload(
        migrated_engine, Artist(spotify_id="ar-rt-genre", name="Washed Out")
    )
    row = persist_and_reload(
        migrated_engine,
        ArtistGenre(genre_id=genre.id, artist_name="Washed Out", artist_id=artist.id, weight=312.5),
    )
    assert isinstance(row.id, int)
    assert isinstance(row.genre_id, int) and row.genre_id == genre.id
    assert row.artist_name == "Washed Out"
    assert isinstance(row.artist_id, int) and row.artist_id == artist.id
    assert row.weight == pytest.approx(312.5)
    assert isinstance(row.weight, float)
    assert_timestamps(row)


def test_feature_calibration_round_trip(migrated_engine: Engine) -> None:
    computed = datetime(2026, 7, 11, 23, 59, 59, 111111)
    row = persist_and_reload(
        migrated_engine,
        FeatureCalibration(
            feature="energy", p10=0.12, p50=0.55, p90=0.91, sample_size=4211, computed_at=computed
        ),
    )
    assert isinstance(row.id, int)
    assert row.feature == "energy"
    assert row.p10 == pytest.approx(0.12)
    assert row.p50 == pytest.approx(0.55)
    assert row.p90 == pytest.approx(0.91)
    assert isinstance(row.p10, float)
    assert row.sample_size == 4211
    assert isinstance(row.sample_size, int)
    assert row.computed_at == computed
    assert isinstance(row.computed_at, datetime)
    assert_timestamps(row)


def test_freqblog_budget_round_trip(migrated_engine: Engine) -> None:
    row = persist_and_reload(migrated_engine, FreqBlogBudget(month="2026-07", used=42))
    assert isinstance(row.id, int)
    assert row.month == "2026-07"
    assert row.used == 42
    assert isinstance(row.used, int)
    assert_timestamps(row)


def test_api_response_cache_round_trip(migrated_engine: Engine) -> None:
    fetched = datetime(2026, 7, 11, 18, 30, 0, 202020)
    payload = {"content": [{"id": "abc", "energy": 0.5, "key": 7}]}
    row = persist_and_reload(
        migrated_engine,
        ApiResponseCache(
            source="reccobeats",
            cache_key="audio-features:6UelLqGlWMcVH1E5c4H7lY",
            payload=payload,
            fetched_at=fetched,
        ),
    )
    assert isinstance(row.id, int)
    assert row.source == "reccobeats"
    assert row.cache_key == "audio-features:6UelLqGlWMcVH1E5c4H7lY"
    assert row.payload == payload
    assert isinstance(row.payload["content"][0]["key"], int)
    assert row.fetched_at == fetched
    assert isinstance(row.fetched_at, datetime)
    assert_timestamps(row)


def test_analytics_snapshot_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-snap")
    playlist = persist_and_reload(
        migrated_engine, Playlist(user_id=user.id, spotify_id="pl-rt-snap", name="rt")
    )
    computed = datetime(2026, 7, 11, 20, 15, 30, 654321)
    payload = {"nodes": [{"id": 1, "centroid": {"energy": 0.42}}], "edges": []}
    row = persist_and_reload(
        migrated_engine,
        AnalyticsSnapshot(
            user_id=user.id,
            kind=SnapshotKind.playlist_analytics,
            playlist_id=playlist.id,
            payload=payload,
            computed_at=computed,
        ),
    )
    assert isinstance(row.id, int)
    assert row.user_id == user.id
    assert row.kind == SnapshotKind.playlist_analytics
    assert isinstance(row.kind, SnapshotKind)
    assert row.playlist_id == playlist.id
    assert row.payload == payload
    assert isinstance(row.payload["nodes"][0]["centroid"]["energy"], float)
    assert row.computed_at == computed
    assert isinstance(row.computed_at, datetime)
    assert_timestamps(row)


def test_analytics_snapshot_library_scope_round_trip(migrated_engine: Engine) -> None:
    user = make_user(migrated_engine, "rt-snap-lib")
    row = persist_and_reload(
        migrated_engine,
        AnalyticsSnapshot(user_id=user.id, kind=SnapshotKind.graph, payload={"nodes": []}),
    )
    assert row.playlist_id is None
    assert row.kind == SnapshotKind.graph


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
