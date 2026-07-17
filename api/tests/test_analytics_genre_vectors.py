"""Per-track genre vector loader (G3).

Builds a per-track genre profile from the ENAO ``ArtistGenre`` join (casefolded
artist-name key), restricted to the library's most-common genres and
L2-normalized so genre contributes a bounded, comparable block to the clustering
distance.
"""

import numpy as np
import pytest
from sqlmodel import Session

from crate.model.orm import ArtistGenre, Genre, Track, User
from crate.services.analytics.loaders import load_genre_vectors

pytestmark = pytest.mark.unit


def _track(session: Session, sid: str, artist: str) -> int:
    row = Track(
        spotify_id=sid, name=f"Track {sid}", artists=[{"spotify_id": f"a-{sid}", "name": artist}]
    )
    session.add(row)
    session.flush()
    assert row.id is not None
    return row.id


def _genre(session: Session, name: str, rank: int, memberships: dict[str, float]) -> None:
    g = Genre(name=name, enao_rank=rank)
    session.add(g)
    session.flush()
    assert g.id is not None
    for artist, weight in memberships.items():
        session.add(ArtistGenre(genre_id=g.id, artist_name=artist, weight=weight))


def test_empty_track_ids_returns_empty(session: Session) -> None:
    vectors, names = load_genre_vectors(session, [])
    assert vectors == {}
    assert names == []


def test_genre_vector_reflects_artist_genres(session: Session, user: User) -> None:
    t_afro = _track(session, "t1", "Burna Boy")
    t_jazz = _track(session, "t2", "Bill Evans")
    _genre(session, "afrobeats", 1, {"burna boy": 3.0})
    _genre(session, "jazz", 2, {"bill evans": 4.0})
    session.commit()

    vectors, names = load_genre_vectors(session, [t_afro, t_jazz])
    assert set(names) == {"afrobeats", "jazz"}
    afro_idx = names.index("afrobeats")
    jazz_idx = names.index("jazz")
    # Afrobeats track loads on the afrobeats axis, zero on jazz (and vice versa).
    assert vectors[t_afro][afro_idx] > 0
    assert vectors[t_afro][jazz_idx] == 0
    assert vectors[t_jazz][jazz_idx] > 0
    # L2-normalized: a single-genre track's vector has unit norm.
    assert np.linalg.norm(vectors[t_afro]) == pytest.approx(1.0)


def test_track_without_genres_is_zero_vector(session: Session, user: User) -> None:
    t_known = _track(session, "t1", "Burna Boy")
    t_unknown = _track(session, "t2", "Nobody")
    _genre(session, "afrobeats", 1, {"burna boy": 3.0})
    session.commit()

    vectors, names = load_genre_vectors(session, [t_known, t_unknown])
    assert names == ["afrobeats"]
    assert np.linalg.norm(vectors[t_unknown]) == 0.0


def test_dims_cap_keeps_top_genres_by_library_weight(session: Session, user: User) -> None:
    t = _track(session, "t1", "Multi")
    # Three genres; cap dims=2 keeps the two heaviest.
    _genre(session, "big", 1, {"multi": 10.0})
    _genre(session, "mid", 2, {"multi": 5.0})
    _genre(session, "small", 3, {"multi": 1.0})
    session.commit()

    _vectors, names = load_genre_vectors(session, [t], dims=2)
    assert set(names) == {"big", "mid"}
    assert "small" not in names
