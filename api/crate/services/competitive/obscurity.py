"""F3 — how niche is this library, and each playlist within it.

Every competitor's obscurity flex (Obscurify, MusicTaste.space) leaned on
Spotify's track ``popularity`` field, which crate never had access to. Instead
crate grounds obscurity in the Every Noise at Once genre ordering it already
ingests: ``Genre.enao_rank`` places each genre on a popularity axis (1 = most
mainstream). A track inherits the rank of its *most mainstream* genre — being
filed under one popular genre is enough to make a track not obscure, even if it
also touches niche corners. A track with no ranked genre is maximally obscure:
nothing on the map places it.

Scores are pure transforms of ``{track_id: [enao_ranks]}`` — the ORM join to
genres lives in the engine. All values are 0..1 (0 = mainstream, 1 = niche).

The Last.fm listener-count upgrade (a per-track absolute audience size) is not
wired: no key is provisioned yet. The report says so (``lastfm_pending``) and
reports its source as ``enao_rank`` — it never fabricates a listener value.
"""

from statistics import mean
from typing import Any

# Size of the Every Noise genre ordering the ``enao_rank`` values index into.
# Rank r maps to a popularity position r / ENAO_GENRE_COUNT, so a genre near
# the tail scores near 1. Every Noise tracked ~6,300 genres; the exact figure
# only sets the resolution of the axis, not its shape.
ENAO_GENRE_COUNT = 6300

# Obscurity when a track has no ranked genre at all — nothing places it on the
# popularity axis, so it reads as maximally niche.
UNRANKED_OBSCURITY = 1.0


def track_obscurity(enao_ranks: list[int]) -> float:
    """Obscurity of one track from its genres' ENAO ranks, 0..1.

    The track inherits the position of its most mainstream (lowest-rank) genre:
    ``min(rank) / ENAO_GENRE_COUNT``. An empty list (no ranked genre) is
    maximally obscure.
    """
    ranks = [r for r in enao_ranks if r and r > 0]
    if not ranks:
        return UNRANKED_OBSCURITY
    return min(min(ranks) / ENAO_GENRE_COUNT, 1.0)


def _pool_score(track_ranks: dict[int, list[int]], track_ids: list[int]) -> dict[str, Any]:
    """Mean track obscurity over a set of track ids (a library or a playlist)."""
    scored = [track_obscurity(track_ranks[tid]) for tid in track_ids if tid in track_ranks]
    return {
        "score": round(mean(scored), 4) if scored else None,
        "scored_tracks": len(scored),
    }


def obscurity_report(
    track_ranks: dict[int, list[int]],
    playlists: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Library obscurity plus a per-playlist breakdown, most obscure first.

    ``track_ranks`` maps every scored library track id to its genres' ENAO
    ranks. ``playlists`` maps playlist id -> ``{name, track_ids}``. A playlist
    (or the library) with no scored tracks reports a null score, never a
    fabricated one.
    """
    library = _pool_score(track_ranks, list(track_ranks))

    playlist_rows: list[dict[str, Any]] = []
    for playlist_id, meta in playlists.items():
        pool = _pool_score(track_ranks, meta.get("track_ids", []))
        playlist_rows.append(
            {
                "playlist_id": playlist_id,
                "name": meta.get("name", ""),
                "score": pool["score"],
                "scored_tracks": pool["scored_tracks"],
            }
        )
    # Most obscure first; unscored playlists (null) sink to the bottom, id-stable.
    playlist_rows.sort(key=lambda p: (p["score"] is None, -(p["score"] or 0.0), p["playlist_id"]))

    return {
        "library": library,
        "playlists": playlist_rows,
        "source": "enao_rank",
        "lastfm_pending": True,
    }
