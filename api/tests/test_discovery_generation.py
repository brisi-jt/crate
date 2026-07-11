"""Candidate generation: sourcing, the library-exclusion property, dedupe.

The exclusion property is load-bearing: nothing already in ANY synced
playlist (by Spotify ID, ISRC, or title+artist) and nothing previously
rejected may ever re-enter the candidate pool.
"""

import pytest
from sqlmodel import Session, select

from crate.model.enums import CandidateSource, CandidateStatus
from crate.model.orm import (
    ArtistGenre,
    DiscoveryCandidate,
    Genre,
    Playlist,
    PlaylistTrack,
    Track,
    User,
)
from crate.services.discovery.generation import (
    dedup_key,
    generate_for_playlist,
    generate_from_genre,
)
from crate.services.enrichment.models import ArtistTopTrack, SimilarArtist
from tests.discovery_fakes import FakeLastFm, FakeRecco, recommended, seed_playlist

pytestmark = pytest.mark.unit


def top_track(name: str, artist: str) -> ArtistTopTrack:
    return ArtistTopTrack(name=name, artist_name=artist)


def similar(name: str, match: float) -> SimilarArtist:
    return SimilarArtist(name=name, match=match)


@pytest.fixture
def gym(session: Session, user: User) -> Playlist:
    return seed_playlist(
        session,
        user,
        "Gym",
        [
            ("t-hyper", "Hyperdrive", "KREAM"),
            ("t-rumble", "Rumble", "Skrillex"),
            ("t-cafune", "CAFUNÉ", "HNTR"),
        ],
    )


def lastfm_for_gym() -> FakeLastFm:
    return FakeLastFm(
        similar={
            "KREAM": [similar("Cassian", 0.9), similar("Vintage Culture", 0.7)],
            "Skrillex": [similar("Fred again..", 0.95)],
            "HNTR": [],
        },
        top_tracks={
            "Cassian": [top_track("Magical", "Cassian"), top_track("Same Things", "Cassian")],
            "Vintage Culture": [top_track("It Is What It Is", "Vintage Culture")],
            "Fred again..": [top_track("Delilah", "Fred again..")],
        },
    )


def candidates_of(session: Session, playlist: Playlist) -> list[DiscoveryCandidate]:
    return list(
        session.exec(
            select(DiscoveryCandidate).where(DiscoveryCandidate.playlist_id == playlist.id)
        ).all()
    )


async def test_lastfm_candidates_carry_provenance(
    session: Session, user: User, gym: Playlist
) -> None:
    report = await generate_for_playlist(
        session, user, gym, lastfm=lastfm_for_gym(), reccobeats=FakeRecco()
    )

    rows = candidates_of(session, gym)
    titles = {(c.title, c.artist) for c in rows}
    assert ("Magical", "Cassian") in titles
    assert ("Delilah", "Fred again..") in titles
    assert all(c.source == CandidateSource.lastfm for c in rows)
    assert all(c.status == CandidateStatus.pending for c in rows)
    magical = next(c for c in rows if c.title == "Magical")
    assert magical.seed_artist == "KREAM"
    assert report.generated_lastfm == len(rows)


async def test_reccobeats_candidates_arrive_resolved(
    session: Session, user: User, gym: Playlist
) -> None:
    recco = FakeRecco(
        recommendations=[recommended("Innerbloom", "RÜFÜS DU SOL", "sp-inner", "AUUM71500123")]
    )
    await generate_for_playlist(session, user, gym, lastfm=None, reccobeats=recco)

    rows = candidates_of(session, gym)
    assert len(rows) == 1
    row = rows[0]
    assert row.source == CandidateSource.reccobeats
    assert row.status == CandidateStatus.resolved
    assert row.spotify_id == "sp-inner"
    assert row.isrc == "AUUM71500123"
    # Seeds were the playlist's opening tracks.
    assert recco.seed_calls == [["t-hyper", "t-rumble", "t-cafune"]]


async def test_no_lastfm_key_degrades_to_reccobeats_only(
    session: Session, user: User, gym: Playlist
) -> None:
    report = await generate_for_playlist(session, user, gym, lastfm=None, reccobeats=FakeRecco())
    assert report.lastfm_skipped is True
    assert report.generated_lastfm == 0


# ------------------------------------------------------- exclusion property


async def test_no_candidate_exists_in_any_synced_playlist(
    session: Session, user: User, gym: Playlist
) -> None:
    """The exclusion property, across ALL the user's playlists."""
    # A second playlist whose tracks the sources will re-suggest.
    seed_playlist(session, user, "Chill", [("t-delilah", "Delilah", "Fred again..")])

    lastfm = lastfm_for_gym()  # suggests Delilah (in Chill) among others
    recco = FakeRecco(
        recommendations=[
            recommended("Hyperdrive", "KREAM", "t-hyper"),  # exact id already in Gym
            recommended("Rumble", "Skrillex", "sp-other-id", "IST-RUMBLE"),  # same isrc
            recommended("Innerbloom", "RÜFÜS DU SOL", "sp-inner"),
        ]
    )
    await generate_for_playlist(session, user, gym, lastfm=lastfm, reccobeats=recco)

    rows = session.exec(
        select(DiscoveryCandidate).where(DiscoveryCandidate.user_id == user.id)
    ).all()

    library_rows = session.exec(
        select(Track)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
        .where(PlaylistTrack.user_id == user.id)
    ).all()
    library_ids = {t.spotify_id for t in library_rows}
    library_isrcs = {t.isrc for t in library_rows if t.isrc}
    library_keys = {
        dedup_key(t.name, t.artists[0]["name"] if t.artists else "") for t in library_rows
    }

    assert rows, "generation produced nothing to check"
    for candidate in rows:
        assert candidate.spotify_id not in library_ids
        assert candidate.isrc is None or candidate.isrc not in library_isrcs
        assert candidate.dedup_key not in library_keys


async def test_isrc_collision_with_library_is_excluded(
    session: Session, user: User, gym: Playlist
) -> None:
    rumble = session.exec(select(Track).where(Track.spotify_id == "t-rumble")).one()
    recco = FakeRecco(
        recommendations=[recommended("Rumble (VIP)", "Skrillex", "sp-vip", rumble.isrc)]
    )
    await generate_for_playlist(session, user, gym, lastfm=None, reccobeats=recco)
    assert candidates_of(session, gym) == []


async def test_rejected_candidates_never_regenerate(
    session: Session, user: User, gym: Playlist
) -> None:
    """Rejected once — for any playlist — means never proposed again."""
    other = seed_playlist(session, user, "Other", [("t-x", "X", "Y")])
    session.add(
        DiscoveryCandidate(
            user_id=user.id,
            playlist_id=other.id,
            source=CandidateSource.lastfm,
            status=CandidateStatus.rejected,
            title="Magical",
            artist="Cassian",
            dedup_key=dedup_key("Magical", "Cassian"),
        )
    )
    session.commit()

    await generate_for_playlist(session, user, gym, lastfm=lastfm_for_gym(), reccobeats=FakeRecco())

    gym_titles = {(c.title, c.artist) for c in candidates_of(session, gym)}
    assert ("Magical", "Cassian") not in gym_titles
    assert ("Same Things", "Cassian") in gym_titles  # only the rejected track is barred


async def test_regeneration_is_idempotent(session: Session, user: User, gym: Playlist) -> None:
    lastfm = lastfm_for_gym()
    await generate_for_playlist(session, user, gym, lastfm=lastfm, reccobeats=FakeRecco())
    first = {c.id for c in candidates_of(session, gym)}
    await generate_for_playlist(session, user, gym, lastfm=lastfm_for_gym(), reccobeats=FakeRecco())
    assert {c.id for c in candidates_of(session, gym)} == first


async def test_dedup_key_folds_case(session: Session) -> None:
    assert dedup_key("Magical", "CASSIAN") == dedup_key("magical", "cassian")


async def test_limit_caps_new_candidates(session: Session, user: User, gym: Playlist) -> None:
    await generate_for_playlist(
        session, user, gym, lastfm=lastfm_for_gym(), reccobeats=FakeRecco(), limit=2
    )
    assert len(candidates_of(session, gym)) == 2


# ---------------------------------------------------------- genre seeding


def seed_genre(session: Session, name: str, members: dict[str, float], rank: int = 1) -> Genre:
    genre = Genre(name=name, enao_rank=rank)
    session.add(genre)
    session.flush()
    assert genre.id is not None
    for artist, weight in members.items():
        session.add(ArtistGenre(genre_id=genre.id, artist_name=artist, weight=weight))
    session.commit()
    return genre


def melodic_house_tracks() -> FakeLastFm:
    return FakeLastFm(
        top_tracks={
            "Cassian": [top_track("Magical", "Cassian"), top_track("Lafayette", "Cassian")],
            "Anyma": [top_track("Explore Your Future", "Anyma")],
        }
    )


async def test_genre_seed_candidates_come_from_non_library_exemplars(
    session: Session, user: User, gym: Playlist
) -> None:
    # KREAM is already in the library — never an exemplar; the fake would
    # explode on an unexpected top-tracks lookup anyway (empty list).
    genre = seed_genre(
        session,
        "melodic house",
        {"Cassian": 100.0, "KREAM": 90.0, "Anyma": 80.0},
    )
    tracks = melodic_house_tracks()

    report = await generate_from_genre(session, user, gym, genre, tracks=tracks)

    rows = candidates_of(session, gym)
    titles = {(c.title, c.artist) for c in rows}
    assert titles == {
        ("Magical", "Cassian"),
        ("Lafayette", "Cassian"),
        ("Explore Your Future", "Anyma"),
    }
    assert all(c.source == CandidateSource.enao for c in rows)
    assert all(c.status == CandidateStatus.pending for c in rows)
    magical = next(c for c in rows if c.title == "Magical")
    assert magical.seed_artist == "Cassian"
    assert report.generated_enao == 3
    # Exemplars walk in descending genre weight.
    assert tracks.calls == [("top_tracks", "Cassian"), ("top_tracks", "Anyma")]


async def test_genre_seed_respects_library_exclusion_and_limit(
    session: Session, user: User, gym: Playlist
) -> None:
    genre = seed_genre(session, "melodic house", {"Cassian": 100.0, "Anyma": 80.0})
    tracks = FakeLastFm(
        top_tracks={
            # Hyperdrive by KREAM is in the library; a proposal naming an
            # in-library track under its exemplar artist still gets through
            # dedupe only when the (title, artist) pair is genuinely new.
            "Cassian": [top_track("Hyperdrive", "KREAM"), top_track("Magical", "Cassian")],
            "Anyma": [top_track("Explore Your Future", "Anyma")],
        }
    )

    report = await generate_from_genre(session, user, gym, genre, tracks=tracks, limit=2)

    rows = candidates_of(session, gym)
    titles = {(c.title, c.artist) for c in rows}
    assert ("Hyperdrive", "KREAM") not in titles  # library exclusion holds
    assert report.excluded == 1
    assert report.generated_enao == 2
    assert len(rows) == 2
