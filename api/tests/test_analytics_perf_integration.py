"""Full analytics recompute at library scale must stay under a minute.

Synthetic library: 60 playlists over 8,000 enriched tracks (roughly JT-sized).
recompute_all covers every payload — graph, track map (UMAP + HDBSCAN),
temporal, library stats, and per-playlist analytics + flow for all 60
playlists — so this is the worst-case wall time a recompute request pays.
"""

import time
from datetime import datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlmodel import Session

from crate.model.enums import FeatureSource, FeatureStatus, PlaylistSyncStatus
from crate.model.orm import Playlist, PlaylistTrack, Track, TrackFeatures, User
from crate.services.analytics.engine import recompute_all
from crate.settings import get_settings
from tests.test_migrations_integration import alembic_config, drop_everything

pytestmark = pytest.mark.integration

TRACKS = 8_000
PLAYLISTS = 60
TRACKS_PER_PLAYLIST = 140
BUDGET_SECONDS = 60.0


def _rng(seed: int):
    import numpy as np

    return np.random.default_rng(seed)


@pytest.fixture(scope="module")
def seeded_engine():
    drop_everything()
    command.upgrade(alembic_config(), "head")
    engine = create_engine(get_settings().database_url)

    rng = _rng(2026)
    base_added = datetime(2023, 1, 1)

    with Session(engine) as session:
        user = User(clerk_user_id="perf-user", spotify_user_id="perf-spotify")
        session.add(user)
        session.flush()

        track_rows = [
            Track(
                spotify_id=f"perf-t{i}",
                isrc=f"PERF{i:09d}",
                name=f"Track {i}",
                artists=[{"spotify_id": f"perf-a{i % 900}", "name": f"Artist {i % 900}"}],
                album_name="Album",
                duration_ms=200_000,
            )
            for i in range(TRACKS)
        ]
        session.add_all(track_rows)
        session.flush()
        track_ids = [row.id for row in track_rows]

        values = rng.random((TRACKS, 9))
        session.add_all(
            TrackFeatures(
                track_id=track_ids[i],
                energy=float(values[i, 0]),
                valence=float(values[i, 1]),
                danceability=float(values[i, 2]),
                acousticness=float(values[i, 3]),
                instrumentalness=float(values[i, 4]),
                liveness=float(values[i, 5]),
                speechiness=float(values[i, 6]),
                tempo=80.0 + 100.0 * float(values[i, 7]),
                loudness=-20.0 + 15.0 * float(values[i, 8]),
                key=int(rng.integers(0, 12)),
                mode=int(rng.integers(0, 2)),
                status=FeatureStatus.present,
                source=FeatureSource.reccobeats,
            )
            for i in range(TRACKS)
        )

        for p in range(PLAYLISTS):
            playlist = Playlist(
                user_id=user.id,
                spotify_id=f"perf-pl{p}",
                name=f"Playlist {p}",
                snapshot_id="snap",
                status=PlaylistSyncStatus.synced,
            )
            session.add(playlist)
            session.flush()
            # Overlapping windows so the graph has edges and subset candidates.
            start = (p * (TRACKS // PLAYLISTS)) % (TRACKS - TRACKS_PER_PLAYLIST)
            members = list(range(start, start + TRACKS_PER_PLAYLIST))
            session.add_all(
                PlaylistTrack(
                    user_id=user.id,
                    playlist_id=playlist.id,
                    track_id=track_ids[t],
                    position=position,
                    added_at=base_added + timedelta(days=int(rng.integers(0, 1200))),
                )
                for position, t in enumerate(members)
            )
        session.commit()
        user_id = user.id

    yield engine, user_id
    engine.dispose()


def test_full_recompute_within_budget(seeded_engine) -> None:
    engine, user_id = seeded_engine

    # Warm numba's JIT on a throwaway projection first: compile time is a
    # per-process constant, not a per-library cost, and production pays it
    # once at worker start, not per recompute.
    import numpy as np

    from crate.services.analytics.clustering import compute_track_map

    warm = np.random.default_rng(0).random((50, 9))
    compute_track_map(warm, list(range(50)), {1: set(range(25)), 2: set(range(25, 50))})

    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        started = time.perf_counter()
        counts = recompute_all(session, user)
        elapsed = time.perf_counter() - started

    # 4 library payloads + analytics + flow per playlist.
    assert counts["computed"] == 4 + 2 * PLAYLISTS
    print(f"\nfull recompute over {PLAYLISTS} playlists / {TRACKS} tracks: {elapsed:.1f}s")
    assert elapsed < BUDGET_SECONDS, f"recompute took {elapsed:.1f}s (budget {BUDGET_SECONDS}s)"
