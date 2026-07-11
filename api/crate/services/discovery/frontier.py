"""Genre territory and frontier over the ENAO layer.

The library's artists anchor it inside the ENAO genre space (1,496 genres,
each with weighted member artists). Three definitions drive everything —
all values are hand-computable from the artist_genres rows:

  w_max(g)          largest membership weight inside genre g (ENAO weights
                    are comparable within a genre, never across genres).

  presence_raw(g) = sum over library artists a in g of  w(a, g) / w_max(g)
                    "how many full-strength member artists' worth of this
                    genre the library holds". presence(g) normalizes by the
                    library's strongest genre, so presence is 0..1.

  adjacency(g, h) = |A_g intersect A_h| / min(|A_g|, |A_h|)
                    containment over the genres' full ENAO artist sets —
                    the same containment convention the playlist graph
                    uses. ENAO ships no explicit genre graph; shared member
                    artists (exemplar lists + sub-genre tag credits folded
                    into artist_genres at import) are its adjacency signal.

  Territory: every genre with presence_raw > 0, ranked by presence.

  Frontier:  genres with presence(g) < FRONTIER_MAX_PRESENCE, scored
             score(g) = [ sum over territory t != g of
                            adjacency(g, t) * presence(t) ] * (1 - presence(g))
             — adjacent to what the library already is, discounted by how
             much of g it already holds. Zero-score genres are dropped.

  Exemplars: each frontier genre's strongest member artists NOT in the
             library, weight normalized to w_max(g).
"""

from typing import Any

from sqlmodel import Session, select

from crate.model.orm import ArtistGenre, Genre, User
from crate.services.analytics.loaders import load_library, load_track_credits

TERRITORY_LIMIT = 40
FRONTIER_LIMIT = 12
EXEMPLAR_LIMIT = 5
ADJACENT_NAMED = 3
# A genre already holding half the library's strongest presence is
# territory, not frontier.
FRONTIER_MAX_PRESENCE = 0.5


def compute_frontier(
    genre_meta: dict[int, tuple[str, int | None]],
    genre_artists: dict[int, dict[str, float]],
    library_keys: set[str],
    *,
    territory_limit: int = TERRITORY_LIMIT,
    frontier_limit: int = FRONTIER_LIMIT,
    exemplar_limit: int = EXEMPLAR_LIMIT,
) -> dict[str, Any]:
    """Territory + frontier from plain structures (see module docstring).

    genre_artists maps genre id -> {artist name as ENAO stores it: weight};
    library_keys are casefolded library artist names (matching is
    case-insensitive). Returns {"territory": [...], "frontier": [...],
    "matched_artists": n}.
    """
    presence_raw: dict[int, float] = {}
    matched_counts: dict[int, int] = {}
    for genre_id, members in genre_artists.items():
        if not members:
            continue
        w_max = max(members.values())
        if w_max <= 0:
            continue
        matched = [key for key in members if key.casefold() in library_keys]
        if matched:
            presence_raw[genre_id] = sum(members[key] / w_max for key in matched)
            matched_counts[genre_id] = len(matched)

    max_raw = max(presence_raw.values(), default=0.0)
    presence = {genre_id: raw / max_raw for genre_id, raw in presence_raw.items()}

    territory_ranked = sorted(
        presence_raw,
        key=lambda genre_id: (-presence[genre_id], genre_meta[genre_id][0]),
    )
    territory = [
        {
            "genre_id": genre_id,
            "name": genre_meta[genre_id][0],
            "enao_rank": genre_meta[genre_id][1],
            "presence": round(presence[genre_id], 4),
            "matched_artists": matched_counts[genre_id],
        }
        for genre_id in territory_ranked[:territory_limit]
    ]

    # Frontier scoring: adjacency to every territory genre, computed via an
    # inverted artist -> genres index restricted to territory members.
    member_sets = {genre_id: set(members) for genre_id, members in genre_artists.items()}
    frontier_entries: list[dict[str, Any]] = []
    for genre_id, members in genre_artists.items():
        genre_presence = presence.get(genre_id, 0.0)
        if genre_presence >= FRONTIER_MAX_PRESENCE or not members:
            continue
        contributions: list[tuple[float, str]] = []
        score_sum = 0.0
        for territory_id in presence_raw:
            if territory_id == genre_id:
                continue
            shared = member_sets[genre_id] & member_sets[territory_id]
            if not shared:
                continue
            adjacency = len(shared) / min(
                len(member_sets[genre_id]), len(member_sets[territory_id])
            )
            contribution = adjacency * presence[territory_id]
            score_sum += contribution
            contributions.append((contribution, genre_meta[territory_id][0]))
        score = score_sum * (1 - genre_presence)
        if score <= 0:
            continue
        contributions.sort(key=lambda item: (-item[0], item[1]))
        w_max = max(members.values())
        exemplars = [
            {"name": name, "weight": round(weight / w_max, 4)}
            for name, weight in sorted(
                (
                    (name, weight)
                    for name, weight in members.items()
                    if name.casefold() not in library_keys
                ),
                key=lambda item: (-item[1], item[0]),
            )[:exemplar_limit]
        ]
        frontier_entries.append(
            {
                "genre_id": genre_id,
                "name": genre_meta[genre_id][0],
                "enao_rank": genre_meta[genre_id][1],
                "score": round(score, 4),
                "presence": round(genre_presence, 4),
                "adjacent_to": [name for _, name in contributions[:ADJACENT_NAMED]],
                "exemplars": exemplars,
            }
        )

    frontier_entries.sort(key=lambda entry: (-entry["score"], entry["name"]))
    return {
        "territory": territory,
        "frontier": frontier_entries[:frontier_limit],
        "matched_artists": len(
            library_keys & {key.casefold() for members in genre_artists.values() for key in members}
        ),
    }


def compute_frontier_payload(
    session: Session, user: User, *, owned_only: bool = True
) -> dict[str, Any]:
    """The /v1/discovery/frontier body: territory, frontier, coverage."""
    assert user.id is not None
    library = load_library(session, user.id, owned_only=owned_only)
    credits = load_track_credits(session, list(library.track_meta))
    library_keys = {name.casefold() for names in credits.values() for name in names}

    genre_meta = {
        genre.id: (genre.name, genre.enao_rank)
        for genre in session.exec(select(Genre)).all()
        if genre.id is not None
    }
    genre_artists: dict[int, dict[str, float]] = {gid: {} for gid in genre_meta}
    rows = session.exec(
        select(ArtistGenre.genre_id, ArtistGenre.artist_name, ArtistGenre.weight)
    ).all()
    for genre_id, artist_name, weight in rows:
        members = genre_artists.get(genre_id)
        if members is not None:
            members[artist_name] = weight

    result = compute_frontier(genre_meta, genre_artists, library_keys)
    return {
        "territory": result["territory"],
        "frontier": result["frontier"],
        "coverage": {
            "library_artists": len(library_keys),
            "matched_artists": result["matched_artists"],
        },
    }
