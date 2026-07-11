"""Radio session building — slot math, flow ordering, seed pools, previews."""

import random

import pytest
from sqlmodel import Session, select

from crate.errors import AppError
from crate.model.enums import (
    CandidateSource,
    CandidateStatus,
    FeedbackAction,
    RadioItemKind,
    RadioSeedKind,
)
from crate.model.orm import (
    ArtistGenre,
    DiscoveryCandidate,
    Genre,
    Playlist,
    PlaylistTrack,
    RadioItem,
    SuggestionFeedback,
    Track,
    TrackFeatures,
    User,
)
from crate.services.analytics.flow import TrackAudio
from crate.services.enrichment.models import DeezerTrack
from crate.services.radio.builder import camelot_label, discovery_slots, flow_order
from crate.services.radio.service import create_radio_session

pytestmark = pytest.mark.unit


# --- pure builder --------------------------------------------------------------


def test_discovery_slots_spread_evenly() -> None:
    assert discovery_slots(total=25, count=5) == [4, 8, 12, 16, 20]
    assert discovery_slots(total=8, count=2) == [2, 5]
    assert discovery_slots(total=10, count=0) == []
    assert discovery_slots(total=0, count=3) == []


def test_discovery_slots_never_collide_or_overflow() -> None:
    for total in range(1, 30):
        for count in range(0, total + 1):
            slots = discovery_slots(total=total, count=count)
            assert len(slots) == len(set(slots)) == count
            assert all(0 <= slot < total for slot in slots)


def test_flow_order_keeps_all_tracks_and_starts_from_the_opener() -> None:
    tracks = [
        TrackAudio(track_id=1, tempo=120.0, key=0, mode=1),
        TrackAudio(track_id=2, tempo=175.0, key=6, mode=0),
        TrackAudio(track_id=3, tempo=122.0, key=0, mode=1),
        TrackAudio(track_id=4, tempo=174.0, key=6, mode=0),
    ]
    order = flow_order(tracks)
    assert sorted(order) == [1, 2, 3, 4]
    assert order[0] == 1
    # The harmonically/tempo-adjacent track follows the opener, not the clash.
    assert order[1] == 3


def test_flow_order_identity_below_three_tracks() -> None:
    tracks = [
        TrackAudio(track_id=7, tempo=None, key=None, mode=None),
        TrackAudio(track_id=8, tempo=None, key=None, mode=None),
    ]
    assert flow_order(tracks) == [7, 8]


def test_camelot_label() -> None:
    assert camelot_label(0, 1) == "8B"  # C major
    assert camelot_label(9, 0) == "8A"  # A minor
    assert camelot_label(None, 1) is None


# --- seeding helpers ------------------------------------------------------------


def seed_track_with_features(
    session: Session,
    spotify_id: str,
    *,
    name: str | None = None,
    artist: str | None = None,
    energy: float = 0.5,
    tempo: float = 120.0,
    key: int = 0,
    mode: int = 1,
) -> Track:
    track = Track(
        spotify_id=spotify_id,
        name=name or f"Track {spotify_id}",
        artists=[{"spotify_id": None, "name": artist or f"Artist {spotify_id}"}],
    )
    session.add(track)
    session.flush()
    session.add(TrackFeatures(track_id=track.id, energy=energy, tempo=tempo, key=key, mode=mode))
    return track


def seed_playlist_with_tracks(
    session: Session, user: User, name: str, count: int, *, energy: float = 0.5
) -> tuple[Playlist, list[Track]]:
    playlist = Playlist(user_id=user.id, spotify_id=f"sp-{name}", name=name, is_owned=True)
    session.add(playlist)
    session.flush()
    tracks = []
    for index in range(count):
        track = seed_track_with_features(session, f"{name}-{index}", energy=energy + index * 0.01)
        session.add(
            PlaylistTrack(
                user_id=user.id, playlist_id=playlist.id, track_id=track.id, position=index
            )
        )
        tracks.append(track)
    session.commit()
    return playlist, tracks


def seed_candidate(
    session: Session,
    user: User,
    playlist: Playlist,
    title: str,
    *,
    energy: float = 0.5,
    preview: str | None = "https://cdn.example/p.mp3",
) -> DiscoveryCandidate:
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        status=CandidateStatus.resolved,
        title=title,
        artist=f"{title} Artist",
        dedup_key=f"{title.casefold()}|x",
        spotify_id=f"cand-{title}",
        preview_url=preview,
        features={"energy": energy, "tempo": 100.0, "key": 5, "mode": 0},
    )
    session.add(candidate)
    session.flush()
    return candidate


class FakePreviews:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None:
        self.calls.append((title, artist))
        if "missing" in title:
            return None
        if "broken" in title:
            raise RuntimeError("deezer down")
        return DeezerTrack(
            id=1, title=title, artist_name=artist, preview=f"https://cdn.example/{title}.mp3"
        )


# --- playlist seed ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_playlist_radio_interleaves_discovery_and_flow_orders_library(
    session: Session, user: User
) -> None:
    playlist, tracks = seed_playlist_with_tracks(session, user, "Gym", 6)
    seed_candidate(session, user, playlist, "candA", energy=0.55)
    seed_candidate(session, user, playlist, "candB", energy=0.52)
    session.commit()

    radio = await create_radio_session(
        session,
        user,
        playlist_id=playlist.id,
        length=10,
        discovery_ratio=0.2,
        previews=None,
        rng=random.Random(0),
    )

    assert radio.id is not None
    assert radio.seed_kind == RadioSeedKind.playlist
    assert radio.label == "Gym"
    items = session.exec(
        select(RadioItem).where(RadioItem.session_id == radio.id).order_by(RadioItem.position)  # type: ignore[arg-type]
    ).all()
    # 6 library tracks + 2 discovery candidates = 8 positions.
    assert [item.position for item in items] == list(range(8))
    discovery = [item for item in items if item.kind == RadioItemKind.discovery]
    assert [item.position for item in discovery] == discovery_slots(total=8, count=2)
    # Discovery items carry candidate identity and preview.
    assert {item.candidate_id for item in discovery} == {
        c.id for c in session.exec(select(DiscoveryCandidate)).all()
    }
    assert all(item.preview_url for item in discovery)
    library = [item for item in items if item.kind == RadioItemKind.library]
    assert {item.track_id for item in library} == {t.id for t in tracks}
    # Instrument readouts present when audio data exists.
    assert all(item.camelot == "8B" for item in library)
    assert all(item.tempo is not None for item in items)


@pytest.mark.asyncio
async def test_reviewed_candidates_never_enter_a_radio(session: Session, user: User) -> None:
    playlist, _ = seed_playlist_with_tracks(session, user, "Gym", 3)
    fresh = seed_candidate(session, user, playlist, "fresh")
    heard = seed_candidate(session, user, playlist, "heard")
    session.add(
        SuggestionFeedback(
            user_id=user.id,
            candidate_id=heard.id,
            playlist_id=playlist.id,
            artist=heard.artist,
            action=FeedbackAction.skip,
        )
    )
    session.commit()

    radio = await create_radio_session(
        session,
        user,
        playlist_id=playlist.id,
        length=10,
        discovery_ratio=0.5,
        previews=None,
        rng=random.Random(0),
    )

    items = session.exec(select(RadioItem).where(RadioItem.session_id == radio.id)).all()
    candidate_ids = {item.candidate_id for item in items if item.candidate_id}
    assert candidate_ids == {fresh.id}


@pytest.mark.asyncio
async def test_library_previews_resolved_with_error_isolation(session: Session, user: User) -> None:
    playlist = Playlist(user_id=user.id, spotify_id="sp-mix", name="Mix", is_owned=True)
    session.add(playlist)
    session.flush()
    names = ["good one", "missing one", "broken one"]
    for index, name in enumerate(names):
        track = seed_track_with_features(session, f"m{index}", name=name)
        session.add(
            PlaylistTrack(
                user_id=user.id, playlist_id=playlist.id, track_id=track.id, position=index
            )
        )
    session.commit()
    previews = FakePreviews()

    radio = await create_radio_session(
        session,
        user,
        playlist_id=playlist.id,
        length=5,
        discovery_ratio=0.2,
        previews=previews,
        rng=random.Random(0),
    )

    items = session.exec(select(RadioItem).where(RadioItem.session_id == radio.id)).all()
    by_title = {item.title: item for item in items}
    assert by_title["good one"].preview_url == "https://cdn.example/good one.mp3"
    assert by_title["missing one"].preview_url is None
    assert by_title["broken one"].preview_url is None  # error isolated, build survived


# --- genre seed ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_genre_radio_draws_from_genre_artists_only(session: Session, user: User) -> None:
    genre = Genre(name="trip hop")
    session.add(genre)
    session.flush()
    playlist = Playlist(user_id=user.id, spotify_id="sp-all", name="All", is_owned=True)
    session.add(playlist)
    session.flush()
    inside = seed_track_with_features(session, "in-1", artist="Bonobo")
    outside = seed_track_with_features(session, "out-1", artist="Slayer")
    for position, track in enumerate((inside, outside)):
        session.add(
            PlaylistTrack(
                user_id=user.id, playlist_id=playlist.id, track_id=track.id, position=position
            )
        )
    session.add(ArtistGenre(genre_id=genre.id, artist_name="Bonobo", weight=5.0))
    matching = seed_candidate(session, user, playlist, "candX")
    session.add(ArtistGenre(genre_id=genre.id, artist_name="candX Artist", weight=2.0))
    seed_candidate(session, user, playlist, "candOutside")
    session.commit()

    radio = await create_radio_session(
        session,
        user,
        genre_name="Trip Hop",
        length=10,
        discovery_ratio=0.5,
        previews=None,
        rng=random.Random(0),
    )

    assert radio.seed_kind == RadioSeedKind.genre
    assert radio.seed_genre == "trip hop"
    assert radio.label == "trip hop"
    items = session.exec(select(RadioItem).where(RadioItem.session_id == radio.id)).all()
    assert {item.track_id for item in items if item.track_id} == {inside.id}
    assert {item.candidate_id for item in items if item.candidate_id} == {matching.id}


# --- tracks seed ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracks_radio_orders_library_by_proximity_to_seed_centroid(
    session: Session, user: User
) -> None:
    playlist = Playlist(user_id=user.id, spotify_id="sp-lib", name="Lib", is_owned=True)
    session.add(playlist)
    session.flush()
    seed = seed_track_with_features(session, "seed", energy=0.9)
    near = seed_track_with_features(session, "near", energy=0.85)
    far = seed_track_with_features(session, "far", energy=0.1)
    for position, track in enumerate((seed, near, far)):
        session.add(
            PlaylistTrack(
                user_id=user.id, playlist_id=playlist.id, track_id=track.id, position=position
            )
        )
    session.commit()

    radio = await create_radio_session(
        session,
        user,
        track_ids=[seed.id],
        length=2,
        discovery_ratio=0.0,
        previews=None,
        rng=random.Random(0),
    )

    assert radio.seed_kind == RadioSeedKind.tracks
    assert radio.seed_track_ids == [seed.id]
    items = session.exec(select(RadioItem).where(RadioItem.session_id == radio.id)).all()
    # The 2 nearest tracks to the seed centroid: the seed itself and its neighbour.
    assert {item.track_id for item in items} == {seed.id, near.id}


# --- guardrails ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_radio_with_no_material_raises(session: Session, user: User) -> None:
    playlist = Playlist(user_id=user.id, spotify_id="sp-empty", name="Empty", is_owned=True)
    session.add(playlist)
    session.commit()

    with pytest.raises(AppError) as excinfo:
        await create_radio_session(
            session,
            user,
            playlist_id=playlist.id,
            length=10,
            discovery_ratio=0.2,
            previews=None,
            rng=random.Random(0),
        )
    assert excinfo.value.status == 409
    assert excinfo.value.error_code == "RADIO_NO_MATERIAL"
