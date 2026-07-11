"""Seed the local database with a small demo library for dashboard work.

Creates the dev user with a handful of playlists — overlapping memberships,
a subset pair, one playlist with duplicate entries (dedupe fodder) — plus
audio features for every track so the graph and analytics render with color.
Re-running wipes and rebuilds the demo rows (idempotent by user).

Pair it with CRATE_FAKE_SPOTIFY=1 on the API so playlist writes succeed
without a Spotify credential:

    cd api && uv run python ../scripts/seed_demo.py                 # user: jt-dev
    cd api && uv run python ../scripts/seed_demo.py --user someone
"""

import argparse
import random
import sys
from datetime import datetime, timedelta

from sqlmodel import Session, create_engine, select

from crate.model.enums import PlaylistSyncStatus
from crate.model.orm import (
    AnalyticsSnapshot,
    MutationJournal,
    OpPreview,
    Playlist,
    PlaylistTrack,
    SyncEvent,
    Track,
    TrackFeatures,
    User,
)
from crate.model.orm.base import utcnow
from crate.settings import get_settings

# (name, sound profile) — profiles steer feature values so the acoustic
# color mapping spreads the nodes across the palette.
PLAYLISTS: list[tuple[str, str, int]] = [
    ("Gym", "electronic-hard", 24),
    ("Gym Warmup", "electronic-mid", 8),  # subset of Gym
    ("Techno", "electronic-hard", 20),
    ("Drill", "electronic-dark", 12),
    ("Indie Rock", "band", 18),
    ("Folk", "acoustic", 15),
    ("Chill Acoustic", "acoustic", 14),
    ("Sunday Morning", "acoustic-warm", 12),
    ("Jazz Club", "acoustic-dark", 10),
    ("New Finds", "mixed", 9),
]

PROFILES = {
    "electronic-hard": {"acousticness": 0.05, "energy": 0.9, "valence": 0.6},
    "electronic-mid": {"acousticness": 0.15, "energy": 0.7, "valence": 0.55},
    "electronic-dark": {"acousticness": 0.1, "energy": 0.8, "valence": 0.25},
    "band": {"acousticness": 0.4, "energy": 0.65, "valence": 0.6},
    "acoustic": {"acousticness": 0.85, "energy": 0.35, "valence": 0.55},
    "acoustic-warm": {"acousticness": 0.9, "energy": 0.25, "valence": 0.8},
    "acoustic-dark": {"acousticness": 0.8, "energy": 0.3, "valence": 0.3},
    "mixed": {"acousticness": 0.5, "energy": 0.5, "valence": 0.5},
}

ADJECTIVES = ["Midnight", "Golden", "Broken", "Electric", "Silent", "Neon", "Velvet", "Hollow"]
NOUNS = ["Horizon", "Echo", "Pulse", "River", "Static", "Bloom", "Signal", "Harbor"]
ARTISTS = [
    "KREAM",
    "Bon Iver",
    "M83",
    "Overmono",
    "Big Thief",
    "Floating Points",
    "Nils Frahm",
    "Fontaines D.C.",
    "Peggy Gou",
    "Khruangbin",
]


def wipe_user_rows(session: Session, user: User) -> None:
    for model in (AnalyticsSnapshot, MutationJournal, OpPreview, SyncEvent, PlaylistTrack):
        for row in session.exec(select(model).where(model.user_id == user.id)).all():
            session.delete(row)
    for row in session.exec(select(Playlist).where(Playlist.user_id == user.id)).all():
        session.delete(row)
    session.commit()


def make_track(session: Session, rng: random.Random, index: int, profile: str) -> Track:
    sid = f"demo-{profile}-{index}"
    existing = session.exec(select(Track).where(Track.spotify_id == sid)).first()
    if existing is not None:
        return existing
    name = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
    artist = rng.choice(ARTISTS)
    track = Track(
        spotify_id=sid,
        isrc=f"DEMO{index:08d}",
        name=name,
        artists=[{"spotify_id": f"demo-artist-{artist}", "name": artist}],
        album_name=f"{name} EP",
        duration_ms=rng.randint(150_000, 320_000),
    )
    session.add(track)
    session.flush()

    base = PROFILES[profile]
    session.add(
        TrackFeatures(
            track_id=track.id,
            energy=min(1, max(0, base["energy"] + rng.uniform(-0.15, 0.15))),
            valence=min(1, max(0, base["valence"] + rng.uniform(-0.15, 0.15))),
            danceability=min(1, max(0, base["energy"] + rng.uniform(-0.2, 0.1))),
            acousticness=min(1, max(0, base["acousticness"] + rng.uniform(-0.1, 0.1))),
            instrumentalness=rng.uniform(0, 0.9),
            liveness=rng.uniform(0.05, 0.4),
            speechiness=rng.uniform(0.02, 0.3),
            tempo=rng.uniform(80, 160),
            key=rng.randint(0, 11),
            mode=rng.randint(0, 1),
            loudness=rng.uniform(-14, -4),
        )
    )
    return track


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="jt-dev", help="clerk_user_id of the dev user")
    args = parser.parse_args()

    rng = random.Random(2026)
    engine = create_engine(get_settings().database_url)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.clerk_user_id == args.user)).first()
        if user is None:
            user = User(clerk_user_id=args.user)
            session.add(user)
            session.commit()
            session.refresh(user)
        wipe_user_rows(session, user)

        track_index = 0
        gym_tracks: list[Track] = []
        for name, profile, size in PLAYLISTS:
            playlist = Playlist(
                user_id=user.id,
                spotify_id=f"demo-pl-{name.lower().replace(' ', '-')}",
                name=name,
                snapshot_id=f"demo-snap-{name}",
                is_owned=True,
                status=PlaylistSyncStatus.synced,
                last_synced_at=utcnow(),
            )
            session.add(playlist)
            session.flush()

            tracks: list[Track] = []
            if name == "Gym Warmup":
                tracks = gym_tracks[:size]  # strict subset of Gym
            else:
                for _ in range(size):
                    track_index += 1
                    tracks.append(make_track(session, rng, track_index, profile))
            if name == "Gym":
                gym_tracks = tracks
                # Overlap with Techno comes from Techno reusing two Gym tracks.
            if name == "Techno" and gym_tracks:
                tracks[0:2] = gym_tracks[0:2]
            if name == "Chill Acoustic":
                # Duplicate entries: dedupe preview fodder.
                tracks = [*tracks, tracks[0], tracks[1]]

            added = datetime(2024, 1, 15) + timedelta(days=rng.randint(0, 800))
            for position, track in enumerate(tracks):
                session.add(
                    PlaylistTrack(
                        user_id=user.id,
                        playlist_id=playlist.id,
                        track_id=track.id,
                        position=position,
                        added_at=added + timedelta(days=position * rng.randint(1, 9)),
                    )
                )
        session.commit()
        print(f"Seeded {len(PLAYLISTS)} playlists for user '{args.user}'.")
        print("Run with the API in fake-Spotify mode: CRATE_FAKE_SPOTIFY=1 CRATE_DEV_USER="
              f"{args.user} uv run uvicorn crate.app:app --port 8200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
