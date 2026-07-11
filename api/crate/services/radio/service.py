"""Radio session assembly.

A radio session is an ordered listening run built from one seed — a playlist,
a set of tracks, or a genre. Library material forms the backbone, ordered
with the same Camelot/BPM transition scoring the flow analytics use;
discovery candidates are interleaved at a steady cadence (default one in
five) so new material arrives inside a familiar run. Sessions persist with
their items, so a run plays back exactly as generated.
"""

import random
from typing import Protocol

from sqlmodel import Session, col, func, select

from crate.errors import AppError
from crate.model.enums import CandidateStatus, RadioItemKind, RadioSeedKind
from crate.model.orm import (
    ArtistGenre,
    DiscoveryCandidate,
    Genre,
    Playlist,
    RadioItem,
    RadioSession,
    SuggestionFeedback,
    User,
)
from crate.services.analytics.flow import TrackAudio
from crate.services.analytics.loaders import (
    LibrarySnapshot,
    load_library,
    load_percentile_space,
    load_track_credits,
)
from crate.services.discovery.service import build_suggestion_queue
from crate.services.enrichment.models import DeezerTrack
from crate.services.radio.builder import camelot_label, discovery_slots, euclidean, flow_order

DEFAULT_LENGTH = 25
DEFAULT_DISCOVERY_RATIO = 0.2


class PreviewSource(Protocol):
    async def search_preview(self, title: str, artist: str) -> DeezerTrack | None: ...


def _require_playlist(session: Session, user: User, playlist_id: int) -> Playlist:
    playlist = session.get(Playlist, playlist_id)
    if playlist is None or playlist.user_id != user.id or playlist.is_deleted:
        raise AppError(
            404,
            "Playlist not found",
            detail=f"No playlist with id {playlist_id}.",
            error_code="PLAYLIST_NOT_FOUND",
        )
    return playlist


def _require_genre(session: Session, genre_name: str) -> Genre:
    genre = session.exec(
        select(Genre).where(func.lower(Genre.name) == genre_name.casefold())
    ).first()
    if genre is None:
        raise AppError(
            404,
            "Genre not found",
            detail=f"No genre named {genre_name!r} in the genre atlas.",
            error_code="GENRE_NOT_FOUND",
        )
    return genre


def _genre_artist_names(session: Session, genre: Genre) -> set[str]:
    rows = session.exec(
        select(ArtistGenre.artist_name).where(ArtistGenre.genre_id == genre.id)
    ).all()
    return {name.casefold() for name in rows}


def _vectors(library: LibrarySnapshot, space, track_ids: list[int]) -> dict[int, dict[str, float]]:
    return {tid: space.transform(library.features.get(tid, {})) for tid in track_ids}


def _centroid(vectors: list[dict[str, float]], features: tuple[str, ...]) -> dict[str, float]:
    if not vectors:
        return dict.fromkeys(features, 0.5)
    return {
        feature: sum(vector.get(feature, 0.5) for vector in vectors) / len(vectors)
        for feature in features
    }


def _unheard_candidates(session: Session, user: User) -> list[DiscoveryCandidate]:
    reviewed = set(
        session.exec(
            select(SuggestionFeedback.candidate_id).where(SuggestionFeedback.user_id == user.id)
        ).all()
    )
    rows = session.exec(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.user_id == user.id)
        .where(DiscoveryCandidate.status == CandidateStatus.resolved)
        .order_by(col(DiscoveryCandidate.id))
    ).all()
    return [candidate for candidate in rows if candidate.id not in reviewed]


def _candidate_vector(candidate: DiscoveryCandidate, space) -> dict[str, float]:
    return space.transform(candidate.features or {})


async def create_radio_session(
    session: Session,
    user: User,
    *,
    playlist_id: int | None = None,
    track_ids: list[int] | None = None,
    genre_name: str | None = None,
    length: int = DEFAULT_LENGTH,
    discovery_ratio: float = DEFAULT_DISCOVERY_RATIO,
    previews: PreviewSource | None = None,
    rng: random.Random | None = None,
) -> RadioSession:
    """Build and persist one radio session from exactly one seed.

    Library selection: playlist and genre seeds sample their pool (every
    member already belongs to the vibe); a tracks seed takes the strict
    nearest neighbours of the seed centroid in percentile space. The
    backbone is then flow-ordered; discovery candidates land at evenly
    spaced slots.
    """
    assert user.id is not None
    rng = rng or random.Random()
    seeds_given = sum(x is not None for x in (playlist_id, track_ids, genre_name))
    if seeds_given != 1:
        raise AppError(
            400,
            "Radio needs one seed",
            detail="Seed a radio with exactly one of playlist_id, track_ids, or genre.",
            error_code="RADIO_SEED_INVALID",
        )

    space = load_percentile_space(session)
    library = load_library(session, user.id)

    playlist: Playlist | None = None
    genre: Genre | None = None
    genre_artists: set[str] = set()

    if playlist_id is not None:
        playlist = _require_playlist(session, user, playlist_id)
        pool = sorted(library.memberships.get(playlist_id, set()))
        seed_kind = RadioSeedKind.playlist
        label = playlist.name
    elif genre_name is not None:
        genre = _require_genre(session, genre_name)
        genre_artists = _genre_artist_names(session, genre)
        credits = load_track_credits(session, list(library.track_meta))
        pool = sorted(
            tid
            for tid, names in credits.items()
            if any(name.casefold() in genre_artists for name in names)
        )
        seed_kind = RadioSeedKind.genre
        label = genre.name
    else:
        assert track_ids is not None
        known = [tid for tid in track_ids if tid in library.track_meta]
        if not known:
            raise AppError(
                404,
                "Seed tracks not found",
                detail="None of the given track ids are in the synced library.",
                error_code="TRACK_NOT_FOUND",
            )
        pool = sorted(library.track_meta)
        seed_kind = RadioSeedKind.tracks
        label = f"{len(known)} seed tracks"

    vectors = _vectors(library, space, pool)
    if seed_kind == RadioSeedKind.tracks:
        assert track_ids is not None
        seed_vectors = [vectors[tid] for tid in track_ids if tid in vectors]
    else:
        seed_vectors = list(vectors.values())
    centroid = _centroid(seed_vectors, space.features)

    # --- discovery pool -----------------------------------------------------
    unheard = _unheard_candidates(session, user)
    if seed_kind == RadioSeedKind.playlist:
        assert playlist is not None
        queue = build_suggestion_queue(session, user, playlist)
        heard_free = {candidate.id for candidate in unheard}
        disc_pool = [entry.candidate for entry in queue if entry.candidate.id in heard_free]
    else:
        if seed_kind == RadioSeedKind.genre:
            unheard = [c for c in unheard if c.artist.casefold() in genre_artists]
        disc_pool = sorted(
            unheard,
            key=lambda c: (
                euclidean(_candidate_vector(c, space), centroid, space.features),
                c.id,
            ),
        )

    n_disc = min(round(length * discovery_ratio), len(disc_pool))
    n_lib = min(length - n_disc, len(pool))
    if n_lib + n_disc == 0:
        raise AppError(
            409,
            "Nothing to play",
            detail="The seed has no library tracks or unreviewed candidates to draw from.",
            error_code="RADIO_NO_MATERIAL",
        )

    # --- library backbone ----------------------------------------------------
    def proximity(tid: int) -> tuple[float, int]:
        return euclidean(vectors[tid], centroid, space.features), tid

    if seed_kind == RadioSeedKind.tracks:
        chosen = sorted(pool, key=proximity)[:n_lib]
    else:
        chosen = sorted(rng.sample(pool, n_lib)) if n_lib < len(pool) else list(pool)
    # Open on the track closest to the seed's sound, then follow the flow.
    chosen = sorted(chosen, key=proximity)
    audio = [
        TrackAudio(track_id=tid, tempo=None, key=None, mode=None)
        if tid not in library.audio
        else TrackAudio(
            track_id=tid,
            tempo=library.audio[tid][0],
            key=library.audio[tid][1],
            mode=library.audio[tid][2],
        )
        for tid in chosen
    ]
    ordered_library = flow_order(audio)

    # --- assemble ---------------------------------------------------------------
    discovery_chosen = disc_pool[:n_disc]
    total = n_lib + n_disc
    slots = set(discovery_slots(total=total, count=n_disc))

    radio = RadioSession(
        user_id=user.id,
        seed_kind=seed_kind,
        seed_playlist_id=playlist.id if playlist else None,
        seed_genre=genre.name if genre else None,
        seed_track_ids=(
            [tid for tid in track_ids if tid in library.track_meta] if track_ids else None
        ),
        label=label,
        discovery_ratio=discovery_ratio,
    )
    session.add(radio)
    session.flush()
    assert radio.id is not None

    library_iter = iter(ordered_library)
    discovery_iter = iter(discovery_chosen)
    for position in range(total):
        if position in slots:
            candidate = next(discovery_iter)
            features = candidate.features or {}
            key = features.get("key")
            mode = features.get("mode")
            item = RadioItem(
                session_id=radio.id,
                position=position,
                kind=RadioItemKind.discovery,
                candidate_id=candidate.id,
                title=candidate.title,
                artist=candidate.artist,
                spotify_id=candidate.spotify_id,
                preview_url=candidate.preview_url,
                tempo=features.get("tempo"),
                camelot=camelot_label(
                    int(key) if key is not None else None,
                    int(mode) if mode is not None else None,
                ),
            )
        else:
            tid = next(library_iter)
            meta = library.track_meta[tid]
            tempo, key, mode = library.audio.get(tid, (None, None, None))
            preview_url: str | None = None
            if previews is not None:
                try:
                    result = await previews.search_preview(str(meta["name"]), str(meta["artist"]))
                except Exception:  # one bad lookup never voids the session
                    result = None
                if result is not None and result.preview:
                    preview_url = result.preview
            item = RadioItem(
                session_id=radio.id,
                position=position,
                kind=RadioItemKind.library,
                track_id=tid,
                title=str(meta["name"]),
                artist=str(meta["artist"]),
                spotify_id=str(meta["spotify_id"]) if meta.get("spotify_id") else None,
                preview_url=preview_url,
                tempo=tempo,
                camelot=camelot_label(key, mode),
            )
        session.add(item)

    session.commit()
    session.refresh(radio)
    return radio


def load_radio_items(session: Session, radio: RadioSession) -> list[RadioItem]:
    return list(
        session.exec(
            select(RadioItem)
            .where(RadioItem.session_id == radio.id)
            .order_by(col(RadioItem.position))
        ).all()
    )
