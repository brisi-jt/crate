"""Insights payload builder.

Assembles the full survey (12 analytics + decade/taste-freeze) from one
library load. Reuses the analytics AnalyticsContext for the library snapshot,
percentile space, and per-track vectors; adds genre aggregation (ENAO), release
years, and the SyncEvent dormancy read on top.

Everything is a library percentile (0..1) except tempo (raw BPM ruler) and
release year. Cached via the AnalyticsSnapshot table under SnapshotKind.insights.
"""

from typing import Any

from sqlmodel import Session, col, select

from crate.model.enums import SyncEventType
from crate.model.orm import ArtistGenre, Genre, SyncEvent, Track, User
from crate.model.orm.base import utcnow
from crate.services.analytics.engine import CENTROID_FEATURES, AnalyticsContext
from crate.services.analytics.loaders import load_track_credits
from crate.services.insights import metrics

# ENAO's genre atlas size; genre rarity scales rank against this ceiling.
ENAO_RANK_CEILING = 1496


def _month_key(added_at: Any) -> str | None:
    if added_at is None:
        return None
    return f"{added_at.year:04d}-{added_at.month:02d}"


def _genre_weights(
    session: Session, library_keys: set[str]
) -> tuple[dict[str, float], dict[str, int | None]]:
    """Library genre weight distribution and each genre's ENAO rank.

    Sums ENAO membership weights across the artists the library actually holds
    (case-insensitive name match), so the distribution reflects the library -
    not the whole atlas.
    """
    genre_meta = {
        genre.id: (genre.name, genre.enao_rank)
        for genre in session.exec(select(Genre)).all()
        if genre.id is not None
    }
    weights: dict[str, float] = {}
    ranks: dict[str, int | None] = {}
    rows = session.exec(
        select(ArtistGenre.genre_id, ArtistGenre.artist_name, ArtistGenre.weight)
    ).all()
    for genre_id, artist_name, weight in rows:
        if artist_name.casefold() not in library_keys:
            continue
        meta = genre_meta.get(genre_id)
        if meta is None:
            continue
        name, rank = meta
        weights[name] = weights.get(name, 0.0) + weight
        ranks[name] = rank
    return weights, ranks


def _dormancy_months(session: Session, user_id: int, playlist_ids: list[int]) -> dict[int, int]:
    """Months since the last observed add/remove per playlist, from SyncEvent.

    Playlists with no add/remove event are treated as dormant since their
    membership's newest add elsewhere isn't tracked here - they simply don't
    appear, and the caller falls back to added_at for those.
    """
    if not playlist_ids:
        return {}
    now = utcnow()
    rows = session.exec(
        select(SyncEvent.playlist_id, SyncEvent.observed_at)
        .where(SyncEvent.user_id == user_id)
        .where(col(SyncEvent.playlist_id).in_(playlist_ids))
        .where(col(SyncEvent.event_type).in_([SyncEventType.added, SyncEventType.removed]))
    ).all()
    latest: dict[int, Any] = {}
    for playlist_id, observed_at in rows:
        if playlist_id not in latest or observed_at > latest[playlist_id]:
            latest[playlist_id] = observed_at
    return {
        playlist_id: (now.year - observed.year) * 12 + (now.month - observed.month)
        for playlist_id, observed in latest.items()
    }


def _track_years(session: Session, track_ids: list[int]) -> dict[int, int]:
    """track id -> release_year for tracks that have one."""
    if not track_ids:
        return {}
    years: dict[int, int] = {}
    chunk = 400
    for start in range(0, len(track_ids), chunk):
        rows = session.exec(
            select(Track.id, Track.release_year).where(
                col(Track.id).in_(track_ids[start : start + chunk])
            )
        ).all()
        for track_id, year in rows:
            if track_id is not None and year is not None:
                years[track_id] = year
    return years


def compute_insights_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    """The full insights survey for one user's library.

    Sections are pre-shaped for the fused survey page; every metric carries its
    own coverage so the web can render pending states without guessing.
    """
    assert user.id is not None
    if ctx is None:
        ctx = AnalyticsContext.load(session, user.id, owned_only=owned_only)
    library, vectors = ctx.library, ctx.vectors

    enriched_vectors = list(vectors.values())
    total_tracks = len(library.track_meta)
    enriched_tracks = len(vectors)

    # -- taste identity ----------------------------------------------------
    credits = load_track_credits(session, list(library.track_meta))
    library_keys = {name.casefold() for names in credits.values() for name in names}
    genre_weights, enao_ranks = _genre_weights(session, library_keys)

    entropy = metrics.shannon_entropy(genre_weights)
    effective = metrics.effective_count(entropy)
    sprawl = metrics.gs_score(enriched_vectors)
    mean_rarity, rarest_genres = metrics.genre_rarity(
        genre_weights, enao_ranks, rank_ceiling=ENAO_RANK_CEILING
    )
    typology = metrics.omnivore_typology(effective, sprawl, mean_rarity)
    fingerprint = metrics.acoustic_fingerprint(enriched_vectors)

    # -- sonic signatures --------------------------------------------------
    camelot_audio = [
        (key, mode, vectors.get(track_id, {}).get("valence"))
        for track_id, (_, key, mode) in library.audio.items()
    ]
    mood_pairs = [
        (vector["energy"], vector["valence"])
        for vector in enriched_vectors
        if "energy" in vector and "valence" in vector
    ]
    tempos = [tempo for tempo, _, _ in library.audio.values()]

    # -- oddities ----------------------------------------------------------
    track_list = [
        {
            "track_id": tid,
            "name": meta.get("name", ""),
            "artist": meta.get("artist", ""),
            "duration_ms": None,
        }
        for tid, meta in library.track_meta.items()
    ]
    durations = _track_durations(session, list(library.track_meta))
    for track in track_list:
        track["duration_ms"] = durations.get(track["track_id"])

    # -- archaeology -------------------------------------------------------
    monthly = [
        (
            _month_key(added_at),
            (
                {feature: vectors[track_id][feature] for feature in CENTROID_FEATURES}
                if track_id in vectors
                else None
            ),
        )
        for _, track_id, added_at in library.adds
    ]
    monthly = [(month, centroid) for month, centroid in monthly if month is not None]
    adds_over_time = metrics.monthly_adds(monthly)

    dormancy = _dormancy_months(session, user.id, list(library.playlist_names))
    # Fall back to the newest added_at when a playlist has no add/remove event.
    newest_add: dict[int, Any] = {}
    for playlist_id, _, added_at in library.adds:
        if added_at is not None and (
            playlist_id not in newest_add or added_at > newest_add[playlist_id]
        ):
            newest_add[playlist_id] = added_at
    now = utcnow()
    last_activity: dict[int, tuple[str, Any]] = {}
    for playlist_id, name in library.playlist_names.items():
        if playlist_id in dormancy:
            months = dormancy[playlist_id]
        elif playlist_id in newest_add:
            add = newest_add[playlist_id]
            months = (now.year - add.year) * 12 + (now.month - add.month)
        else:
            continue
        last_activity[playlist_id] = (name, months)
    abandoned = metrics.abandoned_playlists(last_activity)

    # -- eras --------------------------------------------------------------
    years_by_track = _track_years(session, list(library.track_meta))
    era = metrics.era_profile(list(years_by_track.values()), birth_year=user.birth_year)

    return {
        "coverage": {
            "total_tracks": total_tracks,
            "enriched_tracks": enriched_tracks,
            "library_artists": len(library_keys),
            "dated_tracks": len(years_by_track),
            "birth_year_set": user.birth_year is not None,
        },
        "taste_identity": {
            "fingerprint": fingerprint,
            "genre_entropy": {
                "entropy_bits": round(entropy, 4),
                "effective_genres": round(effective, 2),
            },
            "gs_score": round(sprawl, 4) if sprawl is not None else None,
            "typology": {
                "archetype": typology.archetype,
                "genre_breadth": typology.genre_breadth,
                "acoustic_sprawl": typology.acoustic_sprawl,
                "rarity": typology.rarity,
            },
            "genre_shares": metrics.genre_shares(genre_weights),
            "genre_rarity": {"mean_rarity": mean_rarity, "rarest": rarest_genres},
        },
        "sonic_signatures": {
            "camelot": metrics.camelot_distribution(camelot_audio),
            "mood": metrics.mood_grid(mood_pairs),
            "tempo": metrics.tempo_histogram(tempos),
            "ridgelines": metrics.feature_ridgelines(enriched_vectors),
        },
        "archaeology": {
            "adds_over_time": adds_over_time,
            "abandoned_playlists": abandoned,
        },
        "eras": era,
        "extremes": metrics.extremes_board(track_list, vectors),
    }


def _track_durations(session: Session, track_ids: list[int]) -> dict[int, int]:
    if not track_ids:
        return {}
    durations: dict[int, int] = {}
    chunk = 400
    for start in range(0, len(track_ids), chunk):
        rows = session.exec(
            select(Track.id, Track.duration_ms).where(
                col(Track.id).in_(track_ids[start : start + chunk])
            )
        ).all()
        for track_id, duration in rows:
            if track_id is not None and duration is not None:
                durations[track_id] = duration
    return durations
