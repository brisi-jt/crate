"""Resolution: pending candidates -> Spotify tracks, features, previews."""

import pytest
from sqlmodel import Session

from crate.model.enums import CandidateSource, CandidateStatus
from crate.model.orm import DiscoveryCandidate, Playlist, User
from crate.services.discovery.generation import dedup_key
from crate.services.discovery.resolution import (
    FakeSpotifyResolver,
    fetch_candidate_features,
    resolve_candidates,
    resolve_previews,
)
from crate.services.enrichment.models import AudioFeatures
from crate.services.spotify.models import (
    SpotifyAlbumRef,
    SpotifyArtistRef,
    SpotifyExternalIds,
    SpotifyTrack,
)
from tests.discovery_fakes import FakeDeezer, FakeRecco, FakeResolver, seed_playlist

pytestmark = pytest.mark.unit


@pytest.fixture
def gym(session: Session, user: User) -> Playlist:
    return seed_playlist(session, user, "Gym", [("t-a", "Track A", "KREAM")])


def pending(
    session: Session,
    user: User,
    playlist: Playlist,
    title: str,
    artist: str,
    isrc: str | None = None,
) -> DiscoveryCandidate:
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        status=CandidateStatus.pending,
        title=title,
        artist=artist,
        isrc=isrc,
        dedup_key=dedup_key(title, artist),
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def spotify_track(spotify_id: str, name: str, artist: str, isrc: str) -> SpotifyTrack:
    return SpotifyTrack(
        id=spotify_id,
        name=name,
        duration_ms=201_000,
        external_ids=SpotifyExternalIds(isrc=isrc),
        artists=[SpotifyArtistRef(id=f"a-{artist}", name=artist)],
        album=SpotifyAlbumRef(id="alb-1", name="Album One"),
    )


async def test_resolution_by_name_and_artist(session: Session, user: User, gym: Playlist) -> None:
    candidate = pending(session, user, gym, "Magical", "Cassian")
    resolver = FakeResolver(
        {
            'track:"Magical" artist:"Cassian"': [
                spotify_track("sp-magical", "Magical", "Cassian", "AUUM72000001")
            ]
        }
    )

    resolved = await resolve_candidates(session, [candidate], resolver)

    assert resolved == 1
    assert candidate.status == CandidateStatus.resolved
    assert candidate.spotify_id == "sp-magical"
    assert candidate.isrc == "AUUM72000001"
    assert candidate.album_name == "Album One"
    assert candidate.duration_ms == 201_000


async def test_resolution_prefers_isrc_query(session: Session, user: User, gym: Playlist) -> None:
    candidate = pending(session, user, gym, "Magical", "Cassian", isrc="AUUM72000001")
    resolver = FakeResolver(
        {"isrc:AUUM72000001": [spotify_track("sp-magical", "Magical", "Cassian", "AUUM72000001")]}
    )

    await resolve_candidates(session, [candidate], resolver)

    assert resolver.queries[0] == "isrc:AUUM72000001"
    assert candidate.status == CandidateStatus.resolved


async def test_isrc_miss_falls_back_to_name_search(
    session: Session, user: User, gym: Playlist
) -> None:
    candidate = pending(session, user, gym, "Magical", "Cassian", isrc="AUUM72000001")
    resolver = FakeResolver(
        {
            'track:"Magical" artist:"Cassian"': [
                spotify_track("sp-magical", "Magical", "Cassian", "AUUM72000002")
            ]
        }
    )

    await resolve_candidates(session, [candidate], resolver)

    assert resolver.queries == ["isrc:AUUM72000001", 'track:"Magical" artist:"Cassian"']
    assert candidate.status == CandidateStatus.resolved


async def test_no_match_marks_unresolvable(session: Session, user: User, gym: Playlist) -> None:
    candidate = pending(session, user, gym, "Ghost Song", "Nobody")
    await resolve_candidates(session, [candidate], FakeResolver())
    assert candidate.status == CandidateStatus.unresolvable


async def test_fake_resolver_short_circuits_deterministically(
    session: Session, user: User, gym: Playlist
) -> None:
    """Dev/fake mode: same candidate always resolves to the same invented ID."""
    candidate = pending(session, user, gym, "Magical", "Cassian")
    fake = FakeSpotifyResolver()

    first = await fake.search_tracks('track:"Magical" artist:"Cassian"')
    second = await fake.search_tracks('track:"Magical" artist:"Cassian"')

    assert first[0].id == second[0].id
    assert first[0].id is not None and first[0].id.startswith("fake-")

    await resolve_candidates(session, [candidate], fake)
    assert candidate.status == CandidateStatus.resolved
    assert candidate.spotify_id is not None and candidate.spotify_id.startswith("fake-")


async def test_feature_fetch_stores_raw_values(session: Session, user: User, gym: Playlist) -> None:
    candidate = pending(session, user, gym, "Magical", "Cassian")
    candidate.status = CandidateStatus.resolved
    candidate.spotify_id = "sp-magical"
    session.add(candidate)
    session.commit()

    recco = FakeRecco(
        features={"sp-magical": AudioFeatures(energy=0.9, valence=0.6, acousticness=0.05)}
    )
    fetched = await fetch_candidate_features(session, [candidate], recco)

    assert fetched == 1
    assert candidate.features is not None
    assert candidate.features["energy"] == pytest.approx(0.9)
    # Unanswered features are absent, not zero.
    assert "tempo" not in candidate.features


async def test_preview_resolution_fills_urls_and_tolerates_misses(
    session: Session, user: User, gym: Playlist
) -> None:
    hit = pending(session, user, gym, "Magical", "Cassian")
    miss = pending(session, user, gym, "Obscure", "Nobody")
    for c in (hit, miss):
        c.status = CandidateStatus.resolved
        session.add(c)
    session.commit()

    deezer = FakeDeezer({"magical|cassian": "https://cdn.example/preview.mp3"})
    resolved = await resolve_previews(session, [hit, miss], deezer)

    assert resolved == 1
    assert hit.preview_url == "https://cdn.example/preview.mp3"
    assert miss.preview_url is None
