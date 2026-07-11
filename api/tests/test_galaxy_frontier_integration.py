"""Galaxy + frontier payloads over the migrated MySQL schema.

The unit suites prove the math on sqlite; these prove the MySQL-specific
seams — the case-insensitive ENAO name join (func.lower against the real
collation) and the JSON snapshot round-trip for the two new snapshot kinds.
"""

import pytest
from alembic import command
from sqlalchemy import Engine
from sqlmodel import Session, select

from crate.model.enums import PlaylistSyncStatus, SnapshotKind
from crate.model.orm import (
    AnalyticsSnapshot,
    ArtistGenre,
    Genre,
    Playlist,
    PlaylistTrack,
    Track,
    User,
)
from crate.services.analytics.engine import compute_artist_galaxy_payload
from crate.services.analytics.snapshots import get_or_compute
from crate.services.discovery.frontier import compute_frontier_payload
from tests.db_guard import drop_all_tables
from tests.test_migrations_integration import alembic_config

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def migrated_engine(integration_engine: Engine):
    drop_all_tables(integration_engine)
    command.upgrade(alembic_config(), "head")
    return integration_engine


def seed(session: Session) -> User:
    user = User(clerk_user_id="galaxy-int", spotify_user_id="sp-galaxy-int")
    session.add(user)
    session.flush()

    t1 = Track(spotify_id="gi-t1", name="One", artists=[{"name": "Peggy Gou"}])
    t2 = Track(
        spotify_id="gi-t2",
        name="Two",
        artists=[{"name": "Peggy Gou"}, {"name": "Overmono"}],
    )
    session.add(t1)
    session.add(t2)
    session.flush()

    playlist = Playlist(
        user_id=user.id,
        spotify_id="gi-p1",
        name="Club",
        status=PlaylistSyncStatus.synced,
    )
    session.add(playlist)
    session.flush()
    for position, track in enumerate((t1, t2)):
        session.add(
            PlaylistTrack(
                user_id=user.id,
                playlist_id=playlist.id,
                track_id=track.id,
                position=position,
            )
        )

    genre = Genre(name="k-house", enao_rank=7)
    session.add(genre)
    session.flush()
    # Mixed casing on purpose: the join must survive MySQL's collation AND
    # the func.lower comparison identically.
    session.add(ArtistGenre(genre_id=genre.id, artist_name="peggy gou", weight=100.0))
    session.add(ArtistGenre(genre_id=genre.id, artist_name="DJ Extern", weight=80.0))
    session.commit()
    return user


def test_galaxy_payload_over_mysql(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        user = seed(session)
        payload = compute_artist_galaxy_payload(session, user)

    names = {node["name"] for node in payload["nodes"]}
    assert names == {"Peggy Gou", "Overmono"}
    peggy = next(n for n in payload["nodes"] if n["name"] == "Peggy Gou")
    assert peggy["genres"] == ["k-house"]  # lower-cased ENAO row matched
    assert peggy["track_count"] == 2
    assert payload["edges"] == [
        {"source": "overmono", "target": "peggy gou", "kind": "co_playlist", "weight": 1.0}
    ]


def test_frontier_and_snapshot_round_trip_over_mysql(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        user = session.exec(select(User).where(User.clerk_user_id == "galaxy-int")).first() or seed(
            session
        )

        frontier_payload = get_or_compute(
            session,
            user,
            SnapshotKind.frontier,
            lambda: compute_frontier_payload(session, user, owned_only=True),
            owned_only=True,
        )
        assert [t["name"] for t in frontier_payload["territory"]] == ["k-house"]
        assert frontier_payload["coverage"]["matched_artists"] == 1

    # Fresh session: the payload must have survived the JSON column.
    with Session(migrated_engine) as session:
        row = session.exec(
            select(AnalyticsSnapshot).where(AnalyticsSnapshot.kind == SnapshotKind.frontier)
        ).one()
        assert row.payload == frontier_payload
        assert row.owned_only is True
