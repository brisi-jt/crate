"""F-series payload builders: ORM reads that feed the pure metric modules.

Each ``build_*`` loads what it needs once and returns the JSON body its
endpoint serves. These are read-only aggregations — none mutate. The heavier
ones (obscurity, quality, drift) load the library through the same
``load_library`` / ``load_percentile_space`` loaders the analytics engine uses,
so a track's rank stays catalog-wide and consistent across surfaces.

F4 (flow arc) has no builder here: its reorder is computed per-request in the
router from a playlist's tracks and applied through ``MutationService.reorder``,
so it stays with the write path rather than the read aggregations.
"""

from typing import Any

from sqlmodel import Session, col, func, select

from crate.model.enums import ListeningRange, PlayEventSource, TopItemKind
from crate.model.orm import (
    ArtistGenre,
    Genre,
    PlayEvent,
    TopItemsSnapshot,
    Track,
    User,
)
from crate.model.orm.base import utcnow
from crate.services.analytics.loaders import load_library, load_percentile_space
from crate.services.analytics.structure import cohesion
from crate.services.competitive import drift, obscurity, quality, rhythm
from crate.services.competitive.flow_arc import ArcMood, ArcTrack, suggest_arc_order
from crate.services.insights.metrics import FINGERPRINT_FEATURES

# Chunk size for IN(...) reads over track ids / artist names.
_IN_CHUNK = 400

# The features taste-drift compares two selves on. The whole fingerprint set —
# drift is a broad "does my sound differ" reading, not a three-axis colour.
DRIFT_FEATURES: tuple[str, ...] = FINGERPRINT_FEATURES


# ------------------------------------------------------------------ F3 obscurity


def _track_enao_ranks(session: Session, track_ids: list[int]) -> dict[int, list[int]]:
    """track id -> the ENAO ranks of its artists' genres (deduped).

    Joins each track's credited artist names (casefolded, the ENAO working key)
    to ``ArtistGenre`` -> ``Genre.enao_rank``. Tracks whose artists carry no
    ranked genre map to an empty list (maximally obscure per the metric).
    """
    ranks: dict[int, list[int]] = {tid: [] for tid in track_ids}
    if not track_ids:
        return ranks

    # track id -> its casefolded artist keys, and the reverse index.
    track_keys: dict[int, set[str]] = {}
    all_keys: set[str] = set()
    ids = sorted(track_ids)
    for start in range(0, len(ids), _IN_CHUNK):
        chunk = ids[start : start + _IN_CHUNK]
        for track in session.exec(select(Track).where(col(Track.id).in_(chunk))).all():
            assert track.id is not None
            keys = {str(c["name"]).casefold() for c in track.artists if c.get("name")}
            track_keys[track.id] = keys
            all_keys |= keys

    if not all_keys:
        return ranks

    # artist key -> the enao ranks of every genre it belongs to.
    genre_rank = {
        g.id: g.enao_rank
        for g in session.exec(select(Genre)).all()
        if g.id is not None and g.enao_rank is not None
    }
    key_ranks: dict[str, set[int]] = {}
    ordered = sorted(all_keys)
    for start in range(0, len(ordered), _IN_CHUNK):
        chunk = ordered[start : start + _IN_CHUNK]
        rows = session.exec(
            select(ArtistGenre.genre_id, ArtistGenre.artist_name).where(
                func.lower(ArtistGenre.artist_name).in_(chunk)
            )
        ).all()
        for genre_id, artist_name in rows:
            enao = genre_rank.get(genre_id)
            if enao is None:
                continue
            key_ranks.setdefault(artist_name.casefold(), set()).add(enao)

    for tid, keys in track_keys.items():
        collected: set[int] = set()
        for key in keys:
            collected |= key_ranks.get(key, set())
        ranks[tid] = sorted(collected)
    return ranks


def build_obscurity(session: Session, user: User, *, owned_only: bool = True) -> dict[str, Any]:
    assert user.id is not None
    library = load_library(session, user.id, owned_only=owned_only)
    track_ranks = _track_enao_ranks(session, list(library.track_meta))
    playlists = {
        pid: {"name": library.playlist_names[pid], "track_ids": sorted(members)}
        for pid, members in library.memberships.items()
    }
    return obscurity.obscurity_report(track_ranks, playlists)


# --------------------------------------------------------------------- F1 rhythm


def build_rhythm(
    session: Session,
    user: User,
    *,
    range_: str = ListeningRange.all_time.value,
) -> dict[str, Any]:
    """The listening-rhythm dashboard, over the requested play range.

    ``range_`` is ``all_time`` (every play, incl. imported history) or
    ``since_crate`` (``recent``-source plays only). The filter is SQL-side so
    counts reflect exactly the range in view.
    """
    assert user.id is not None
    stmt = (
        select(PlayEvent, Track)
        .where(PlayEvent.user_id == user.id)
        .where(PlayEvent.track_id == Track.id)
    )
    if range_ == ListeningRange.since_crate.value:
        stmt = stmt.where(PlayEvent.source == PlayEventSource.recent)
    rows = session.exec(stmt).all()

    plays = [
        {"track_id": play.track_id, "played_at": play.played_at, "ms_played": play.ms_played}
        for play, _track in rows
    ]
    track_meta = {
        track.id: {"name": track.name, "artist": _primary_artist(track)}
        for _play, track in rows
        if track.id is not None
    }
    payload = rhythm.rhythm_report(plays, track_meta)
    payload["range"] = range_
    return payload


def _primary_artist(track: Track) -> str:
    names = [str(c["name"]) for c in track.artists if c.get("name")]
    return names[0] if names else ""


# ---------------------------------------------------------------------- F5 drift


def build_drift(
    session: Session,
    user: User,
    *,
    snapshot_id: int | None = None,
    owned_only: bool = True,
) -> dict[str, Any]:
    """Available snapshot timeline plus, when one is chosen, the drift comparison.

    The "then" fingerprint is the mean feature vector of a top-tracks snapshot's
    tracks (resolved to the catalog); the "now" fingerprint is the current
    library's. Only track snapshots carry resolvable audio; artist snapshots
    appear in the timeline for context but aren't comparable.
    """
    assert user.id is not None
    snapshots = session.exec(
        select(TopItemsSnapshot)
        .where(TopItemsSnapshot.user_id == user.id)
        .order_by(col(TopItemsSnapshot.captured_at).desc())
    ).all()
    timeline = [
        {
            "snapshot_id": snap.id,
            "kind": snap.kind.value,
            "time_range": snap.time_range.value,
            "captured_at": snap.captured_at.isoformat(),
            "comparable": snap.kind == TopItemKind.track,
        }
        for snap in snapshots
    ]

    space = load_percentile_space(session)
    library = load_library(session, user.id, owned_only=owned_only)
    now_vectors = {tid: space.transform(v) for tid, v in library.features.items()}
    now_fp = drift.fingerprint_of(list(now_vectors), now_vectors, DRIFT_FEATURES)

    comparison = None
    chosen = next((s for s in snapshots if s.id == snapshot_id), None) if snapshot_id else None
    if chosen is not None and chosen.kind == TopItemKind.track:
        then_fp = _snapshot_fingerprint(session, chosen, now_vectors)
        comparison = drift.fingerprint_delta(now_fp, then_fp, DRIFT_FEATURES)

    return {
        "timeline": timeline,
        "now_fingerprint": now_fp,
        "selected_snapshot_id": snapshot_id,
        "comparison": comparison,
    }


def _snapshot_fingerprint(
    session: Session,
    snapshot: TopItemsSnapshot,
    catalog_vectors: dict[int, dict[str, float]],
) -> dict[str, float] | None:
    """Fingerprint of a track snapshot: resolve its spotify ids, mean their vectors."""
    spotify_ids = [str(item["spotify_id"]) for item in snapshot.items if item.get("spotify_id")]
    if not spotify_ids:
        return None
    rows = session.exec(select(Track).where(col(Track.spotify_id).in_(spotify_ids))).all()
    track_ids = [t.id for t in rows if t.id is not None]
    return drift.fingerprint_of(track_ids, catalog_vectors, DRIFT_FEATURES)


# -------------------------------------------------------------------- F6 quality


def build_quality(session: Session, user: User, *, owned_only: bool = True) -> dict[str, Any]:
    """Per-playlist quality (cohesion / uniqueness / freshness / flow)."""
    import numpy as np

    from crate.services.analytics.flow import flow_score

    assert user.id is not None
    library = load_library(session, user.id, owned_only=owned_only)
    space = load_percentile_space(session)
    vectors = {tid: space.transform(v) for tid, v in library.features.items()}
    now = utcnow()

    # Newest add per playlist (freshness input).
    newest: dict[int, Any] = {}
    for playlist_id, _track_id, added_at in library.adds:
        if added_at is None:
            continue
        current = newest.get(playlist_id)
        if current is None or added_at > current:
            newest[playlist_id] = added_at

    playlists: list[dict[str, Any]] = []
    for playlist_id in sorted(library.playlist_names):
        members = library.memberships.get(playlist_id, set())
        occ = library.occurrences.get(playlist_id, [])

        enriched = sorted(tid for tid in members if tid in vectors)
        matrix = np.array(
            [[vectors[tid][f] for f in space.features] for tid in enriched], dtype=float
        ).reshape(len(enriched), len(space.features))
        playlist_cohesion = cohesion(matrix)

        dup_fraction = _duplicate_fraction(occ, library.track_meta)

        ordered = [_track_audio(library, tid) for tid in occ]
        flow = flow_score(ordered)

        result = quality.playlist_quality(
            cohesion=playlist_cohesion,
            duplicate_fraction=dup_fraction,
            newest_added_at=newest.get(playlist_id),
            flow_score=flow,
            now=now,
        )
        playlists.append(
            {
                "playlist_id": playlist_id,
                "name": library.playlist_names[playlist_id],
                "track_count": len(occ),
                "score": result["score"],
                "subscores": result["subscores"],
            }
        )

    playlists.sort(key=lambda p: (p["score"] is None, -(p["score"] or 0.0), p["playlist_id"]))
    return {"playlists": playlists, "subscore_refs": list(quality.SUBSCORE_REFS)}


def _track_audio(library: Any, track_id: int) -> "Any":
    from crate.services.analytics.flow import TrackAudio

    tempo, key, mode = library.audio.get(track_id, (None, None, None))
    return TrackAudio(track_id=track_id, tempo=tempo, key=key, mode=mode)


def _duplicate_fraction(
    occurrences: list[int], track_meta: dict[int, dict[str, Any]]
) -> float | None:
    """Share of a playlist's slots taken by a repeat.

    A slot is a duplicate when its track id already appeared earlier in the
    playlist, or when its recording (ISRC) already appeared under a different
    track id — the two duplicate shapes Spotify's own dedupe misses. None for an
    empty playlist (nothing to score).
    """
    if not occurrences:
        return None
    seen_tracks: set[int] = set()
    seen_isrcs: set[str] = set()
    duplicates = 0
    for track_id in occurrences:
        isrc = track_meta.get(track_id, {}).get("isrc")
        if track_id in seen_tracks or (isrc and isrc in seen_isrcs):
            duplicates += 1
        seen_tracks.add(track_id)
        if isrc:
            seen_isrcs.add(isrc)
    return duplicates / len(occurrences)


# ------------------------------------------------------------------- F4 flow arc


def build_arc_preview(
    session: Session,
    user: User,
    playlist_id: int,
    *,
    mood: str,
    owned_only: bool = True,
) -> dict[str, Any] | None:
    """A proposed mood-arc reorder for a playlist — READ-ONLY (no write).

    Loads the playlist's tracks in current order, builds ArcTracks (energy
    percentile + primary-artist key), and runs the arc + separation reorder.
    Returns the suggested order, the current and suggested base-flow scores, and
    the artist-separation quality — or None below the three-track floor. The
    router applies an accepted order through ``MutationService.reorder`` (the
    existing journaled write path); this function never mutates.
    """
    from crate.services.analytics.flow import flow_score

    assert user.id is not None
    library = load_library(session, user.id, owned_only=owned_only)
    if playlist_id not in library.playlist_names:
        return None
    space = load_percentile_space(session)
    vectors = {tid: space.transform(v) for tid, v in library.features.items()}

    occ = library.occurrences.get(playlist_id, [])
    arc_tracks: list[ArcTrack] = []
    for tid in occ:
        tempo, key, mode = library.audio.get(tid, (None, None, None))
        energy = vectors.get(tid, {}).get("energy", 0.5)
        artist = library.track_meta.get(tid, {}).get("artist", "")
        arc_tracks.append(
            ArcTrack(
                track_id=tid,
                tempo=tempo,
                key=key,
                mode=mode,
                energy=energy,
                artist_key=str(artist).casefold(),
            )
        )

    suggestion = suggest_arc_order(arc_tracks, mood=ArcMood(mood))
    if suggestion is None:
        return None

    current_audio = [_track_audio(library, tid) for tid in occ]
    current_flow = flow_score(current_audio)
    return {
        "playlist_id": playlist_id,
        "name": library.playlist_names[playlist_id],
        "mood": mood,
        "suggested_order": suggestion.order,
        "current_flow": round(current_flow, 2) if current_flow is not None else None,
        "suggested_flow": suggestion.flow_score,
        "adjacent_artist_repeats": suggestion.adjacent_artist_repeats,
    }
