"""Extended-insights payload builder (I1-I24).

Mines the tables the original survey never read - play_events, saved_tracks,
suggestion_feedback, discovery_candidates, top_items_snapshots, radio_*,
mutation_journal, feature_calibrations - and assembles one section-shaped
payload. Reuses AnalyticsContext for the library snapshot, percentile space,
and per-track vectors; every extra table is loaded once here (ORM stays out of
metrics_extended, which is pure).

Cached via the AnalyticsSnapshot table under SnapshotKind.insights_extended.
All feature-derived numbers are library percentiles (0..1); play counts, spreads
and rates are plain scalars. Sections carry their own coverage so the web renders
pending states without guessing.
"""

from datetime import timedelta
from typing import Any

from sqlmodel import Session, col, func, select

from crate.model.enums import (
    BulkOperation,
    CandidateStatus,
    FeedbackAction,
    MutationStatus,
    PlayEventSource,
    RadioItemFeedback,
    RadioItemKind,
    TopItemKind,
    TopTimeRange,
)
from crate.model.orm import (
    DiscoveryCandidate,
    FeatureCalibration,
    MutationJournal,
    PlayEvent,
    Playlist,
    RadioItem,
    RadioSession,
    SavedTrack,
    SuggestionFeedback,
    TopItemsSnapshot,
    Track,
    User,
)
from crate.model.orm.base import utcnow
from crate.services.analytics.engine import AnalyticsContext
from crate.services.insights import metrics_extended as mx

# Tracks added inside this window count as "recent" for the rotation-velocity
# reading (I3): plays on them are new-arrival listening vs deep-catalog listening.
RECENCY_WINDOW_DAYS = 90

# A track filed in this many or more owned playlists is a "hit" within the
# library; fewer makes it a deep cut (I6).
HIT_MEMBERSHIP_THRESHOLD = 3

# Chunk size for IN(...) queries over ids.
_IN_CHUNK = 400


def _playlist_id_by_spotify(session: Session, user_id: int) -> dict[str, int]:
    """spotify_id -> local playlist id for the user's live playlists."""
    rows = session.exec(
        select(Playlist.spotify_id, Playlist.id)
        .where(Playlist.user_id == user_id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
    ).all()
    return {spotify_id: pid for spotify_id, pid in rows if pid is not None}


def _playlist_from_context_uri(uri: str | None, by_spotify: dict[str, int]) -> int | None:
    """Map a `spotify:playlist:<id>` context uri to a local playlist id."""
    if not uri or not uri.startswith("spotify:playlist:"):
        return None
    return by_spotify.get(uri.rsplit(":", 1)[-1])


def _play_events_section(
    session: Session,
    user: User,
    ctx: AnalyticsContext,
    by_spotify: dict[str, int],
) -> tuple[dict[str, Any], dict[int, int], int]:
    """I1-I6: everything derived from play_events for this user.

    Returns (section, per-playlist play counts (for I22), total plays).
    """
    library, vectors = ctx.library, ctx.vectors
    rows = session.exec(select(PlayEvent).where(PlayEvent.user_id == user.id)).all()

    play_counts: dict[int, int] = {}
    played_at: list[Any] = []
    context_types: list[str | None] = []
    mood_events: list[tuple[Any, dict[str, float]]] = []
    playlist_play_counts: dict[int, int] = {}
    for event in rows:
        play_counts[event.track_id] = play_counts.get(event.track_id, 0) + 1
        played_at.append(event.played_at)
        context_types.append(event.context_type)
        vector = vectors.get(event.track_id)
        if vector is not None:
            mood_events.append((event.played_at, vector))
        pid = _playlist_from_context_uri(event.context_uri, by_spotify)
        if pid is not None:
            playlist_play_counts[pid] = playlist_play_counts.get(pid, 0) + 1

    membership_counts: dict[int, int] = {}
    for track_ids in library.memberships.values():
        for tid in track_ids:
            membership_counts[tid] = membership_counts.get(tid, 0) + 1

    # Recent adds: any track added to an owned playlist inside the window.
    cutoff = utcnow() - timedelta(days=RECENCY_WINDOW_DAYS)
    recent_track_ids = {
        track_id
        for _, track_id, added_at in library.adds
        if added_at is not None and added_at >= cutoff
    }

    section = {
        "play_collect_gap": mx.play_collect_gap(play_counts, membership_counts, library.track_meta),
        "listening_clock": mx.listening_clock(played_at),
        "rotation_velocity": mx.rotation_velocity(play_counts, recent_track_ids),
        "context_mix": mx.context_mix(context_types),
        "play_mood_by_hour": mx.play_mood_by_hour(mood_events),
        "deep_cuts_vs_hits": mx.deep_cuts_vs_hits(
            play_counts, membership_counts, hit_threshold=HIT_MEMBERSHIP_THRESHOLD
        ),
    }
    return section, playlist_play_counts, len(rows)


def _saved_section(
    session: Session, user: User, ctx: AnalyticsContext
) -> tuple[dict[str, Any], int]:
    """I7-I10: saved_tracks fingerprint, latency, churn, orphans."""
    library, vectors = ctx.library, ctx.vectors
    saved_rows = session.exec(select(SavedTrack).where(SavedTrack.user_id == user.id)).all()
    total_saves = len(saved_rows)
    removed = sum(1 for row in saved_rows if row.is_removed)
    active = [row for row in saved_rows if not row.is_removed]
    active_ids = {row.track_id for row in active}

    filed_ids = {tid for track_ids in library.memberships.values() for tid in track_ids}

    liked_vectors = [vectors[tid] for tid in active_ids if tid in vectors]
    playlist_vectors = [vectors[tid] for tid in filed_ids if tid in vectors]

    # I8 save->file latency: for tracks that are both saved and filed, days from
    # saved_at to the track's earliest playlist add.
    earliest_add: dict[int, Any] = {}
    for _, track_id, added_at in library.adds:
        if added_at is None:
            continue
        if track_id not in earliest_add or added_at < earliest_add[track_id]:
            earliest_add[track_id] = added_at
    latencies: list[float] = []
    for row in active:
        if row.saved_at is None:
            continue
        added = earliest_add.get(row.track_id)
        if added is None:
            continue
        latencies.append((added - row.saved_at).total_seconds() / 86400.0)

    section = {
        "liked_vs_playlist": mx.liked_vs_playlist_fingerprint(liked_vectors, playlist_vectors),
        "save_file_latency": mx.save_file_latency(latencies),
        "unsave_churn": mx.unsave_churn(total_saves=total_saves, removed=removed),
        "orphan_saves": mx.orphan_saves(
            saved_ids=active_ids, filed_ids=filed_ids, track_meta=library.track_meta
        ),
        "total_saved": len(active_ids),
    }
    return section, total_saves


def _feedback_section(session: Session, user: User, ctx: AnalyticsContext) -> dict[str, Any]:
    """I11-I14: suggestion feedback + discovery candidate funnel."""
    feedback_rows = session.exec(
        select(SuggestionFeedback, DiscoveryCandidate)
        .where(SuggestionFeedback.user_id == user.id)
        .where(SuggestionFeedback.candidate_id == DiscoveryCandidate.id)
    ).all()

    # I11 source efficacy: accept/reject/skip per candidate source.
    source_tallies: dict[str, dict[str, int]] = {}
    artist_tallies: dict[str, dict[str, int]] = {}
    curation_totals = {action.value: 0 for action in FeedbackAction}
    # I12 taste-of-yes: accepted vs rejected candidate feature vectors. Candidate
    # features are raw ReccoBeats dicts; rank them through the catalog space.
    accepted_vectors: list[dict[str, float]] = []
    rejected_vectors: list[dict[str, float]] = []
    space = ctx.space
    for feedback, candidate in feedback_rows:
        action = feedback.action.value
        curation_totals[action] = curation_totals.get(action, 0) + 1
        source = candidate.source.value
        source_tallies.setdefault(source, {"accept": 0, "reject": 0, "skip": 0})
        source_tallies[source][action] = source_tallies[source].get(action, 0) + 1
        artist_tallies.setdefault(feedback.artist, {"accept": 0, "reject": 0})
        if action in artist_tallies[feedback.artist]:
            artist_tallies[feedback.artist][action] += 1
        if candidate.features:
            ranked = space.transform(candidate.features)
            if feedback.action is FeedbackAction.accept:
                accepted_vectors.append(ranked)
            elif feedback.action is FeedbackAction.reject:
                rejected_vectors.append(ranked)

    # I14 candidate funnel: status counts across the user's candidates.
    status_rows = session.exec(
        select(DiscoveryCandidate.status, func.count())
        .where(DiscoveryCandidate.user_id == user.id)
        .group_by(DiscoveryCandidate.status)
    ).all()
    status_counts = {
        (status.value if isinstance(status, CandidateStatus) else str(status)): int(count)
        for status, count in status_rows
    }

    return {
        "source_efficacy": mx.source_efficacy(source_tallies),
        "taste_of_yes": mx.taste_of_yes(accepted_vectors, rejected_vectors),
        "per_artist_affinity": mx.per_artist_affinity(artist_tallies),
        "candidate_funnel": mx.candidate_funnel(status_counts),
        "curation_totals": curation_totals,
    }


def _resolve_snapshot_vectors(
    session: Session, ctx: AnalyticsContext, items: list[dict[str, Any]]
) -> list[dict[str, float]]:
    """Percentile vectors for the catalog tracks named by a top-items snapshot."""
    spotify_ids = [item["spotify_id"] for item in items if item.get("spotify_id")]
    if not spotify_ids:
        return []
    id_by_spotify: dict[str, int] = {}
    for start in range(0, len(spotify_ids), _IN_CHUNK):
        chunk = spotify_ids[start : start + _IN_CHUNK]
        for track in session.exec(
            select(Track.spotify_id, Track.id).where(col(Track.spotify_id).in_(chunk))
        ).all():
            if track[1] is not None:
                id_by_spotify[track[0]] = track[1]
    vectors = ctx.vectors
    return [
        vectors[id_by_spotify[sid]]
        for sid in spotify_ids
        if sid in id_by_spotify and id_by_spotify[sid] in vectors
    ]


def _top_items_section(session: Session, user: User, ctx: AnalyticsContext) -> dict[str, Any]:
    """I15-I17: top-items sound vs library, affinity churn, short/long divergence."""
    vectors = ctx.vectors
    snapshots = session.exec(
        select(TopItemsSnapshot)
        .where(TopItemsSnapshot.user_id == user.id)
        .order_by(col(TopItemsSnapshot.captured_at))
    ).all()

    # I15: latest track snapshot (any range, prefer medium) vs whole library.
    track_snaps = [s for s in snapshots if s.kind is TopItemKind.track]
    latest_track = track_snaps[-1] if track_snaps else None
    top_vectors = (
        _resolve_snapshot_vectors(session, ctx, latest_track.items) if latest_track else []
    )
    library_vectors = list(vectors.values())

    # I16 affinity churn: successive artist snapshots (medium range) Jaccard.
    def _series(kind: TopItemKind, time_range: TopTimeRange) -> list[list[str]]:
        seq = [
            [str(item.get("spotify_id") or item.get("name")) for item in s.items]
            for s in snapshots
            if s.kind is kind and s.time_range is time_range
        ]
        return seq

    churn_series = _series(TopItemKind.artist, TopTimeRange.medium)

    # I17 short vs long divergence: latest short vs latest long artist snapshot.
    def _latest_ids(kind: TopItemKind, time_range: TopTimeRange) -> list[str]:
        matching = [s for s in snapshots if s.kind is kind and s.time_range is time_range]
        if not matching:
            return []
        return [str(item.get("spotify_id") or item.get("name")) for item in matching[-1].items]

    short_ids = _latest_ids(TopItemKind.artist, TopTimeRange.short)
    long_ids = _latest_ids(TopItemKind.artist, TopTimeRange.long)

    return {
        "top_vs_library": mx.top_items_sound(top_vectors, library_vectors),
        "affinity_churn": mx.affinity_churn(churn_series),
        "short_vs_long": mx.short_vs_long_divergence(short=short_ids, long=long_ids),
        "snapshot_count": len(snapshots),
    }


def _radio_section(session: Session, user: User) -> dict[str, Any]:
    """I18-I19: radio keep rate by seed kind, discovery conversion."""
    rows = session.exec(
        select(RadioItem, RadioSession)
        .where(RadioItem.session_id == RadioSession.id)
        .where(RadioSession.user_id == user.id)
    ).all()

    per_seed: dict[str, dict[str, int]] = {}
    discovery_total = 0
    discovery_kept = 0
    for item, session_row in rows:
        seed = session_row.seed_kind.value
        per_seed.setdefault(seed, {"kept": 0, "skipped": 0})
        if item.feedback is RadioItemFeedback.kept:
            per_seed[seed]["kept"] += 1
        elif item.feedback is RadioItemFeedback.skipped:
            per_seed[seed]["skipped"] += 1
        if item.kind is RadioItemKind.discovery:
            discovery_total += 1
            if item.feedback is RadioItemFeedback.kept:
                discovery_kept += 1

    return {
        "keep_rate": mx.radio_keep_rate(per_seed),
        "discovery_conversion": mx.discovery_conversion(
            discovery_total=discovery_total, discovery_kept=discovery_kept
        ),
    }


def _journal_section(session: Session, user: User) -> dict[str, Any]:
    """I20-I21: curation intensity + bulk-algebra usage from the mutation journal."""
    rows = session.exec(
        select(MutationJournal)
        .where(MutationJournal.user_id == user.id)
        .order_by(col(MutationJournal.created_at))
    ).all()

    op_counts: dict[str, int] = {}
    bulk_counts: dict[str, int] = {}
    undone = 0
    for row in rows:
        op_counts[row.op_type.value] = op_counts.get(row.op_type.value, 0) + 1
        if row.status is MutationStatus.undone:
            undone += 1
        # Bulk applies record their set operation in the payload.
        if row.op_type.value == "bulk":
            operation = row.payload.get("operation")
            if operation in {op.value for op in BulkOperation}:
                bulk_counts[operation] = bulk_counts.get(operation, 0) + 1

    total = len(rows)
    weeks = 0.0
    if total >= 2 and rows[0].created_at and rows[-1].created_at:
        span_days = (rows[-1].created_at - rows[0].created_at).total_seconds() / 86400.0
        weeks = max(span_days / 7.0, 0.0)

    return {
        "curation_intensity": mx.curation_intensity(
            op_counts, undone=undone, total=total, weeks=weeks
        ),
        "bulk_algebra": mx.bulk_algebra_usage(bulk_counts),
    }


def _cross_table_section(
    session: Session,
    ctx: AnalyticsContext,
    playlist_play_counts: dict[int, int],
) -> dict[str, Any]:
    """I22-I24: listened-vs-neglected, calibration drift, era-of-add vs release."""
    library = ctx.library

    # I22: dormancy per owned playlist, crossed with attributed plays.
    dormancy = _dormancy_by_playlist(library)
    listened = mx.listened_vs_neglected(playlist_play_counts, dormancy)

    # I23 calibration drift: FeatureCalibration stores one current row per
    # feature (no time series exists), so this renders the current p10-p90
    # spread as a single point per feature; spread_delta stays null until a
    # calibration-history table lands. See handoff (documented deviation).
    calib_rows = session.exec(select(FeatureCalibration)).all()
    series = [
        {
            "captured_at": row.computed_at.isoformat(),
            "feature": row.feature,
            "p10": row.p10,
            "p90": row.p90,
        }
        for row in calib_rows
    ]
    drift = mx.calibration_drift(series)

    # I24 era-of-add vs era-of-release: (add year, release year) per filed track.
    years = _release_years(session, list(library.track_meta))
    pairs: list[tuple[int, int]] = []
    seen: set[int] = set()
    for _, track_id, added_at in library.adds:
        if added_at is None or track_id in seen:
            continue
        release_year = years.get(track_id)
        if release_year is None:
            continue
        seen.add(track_id)
        pairs.append((added_at.year, release_year))
    era = mx.era_add_vs_release(pairs)

    return {
        "listened_vs_neglected": listened,
        "calibration_drift": drift,
        "era_add_vs_release": era,
    }


def _dormancy_by_playlist(library: Any) -> dict[int, tuple[str, int]]:
    """playlist id -> (name, months since its newest add) over owned playlists."""
    now = utcnow()
    newest_add: dict[int, Any] = {}
    for playlist_id, _, added_at in library.adds:
        if added_at is not None and (
            playlist_id not in newest_add or added_at > newest_add[playlist_id]
        ):
            newest_add[playlist_id] = added_at
    result: dict[int, tuple[str, int]] = {}
    for playlist_id, name in library.playlist_names.items():
        add = newest_add.get(playlist_id)
        months = 0 if add is None else (now.year - add.year) * 12 + (now.month - add.month)
        result[playlist_id] = (name, months)
    return result


def _release_years(session: Session, track_ids: list[int]) -> dict[int, int]:
    """track id -> release_year for tracks that have one."""
    if not track_ids:
        return {}
    years: dict[int, int] = {}
    for start in range(0, len(track_ids), _IN_CHUNK):
        rows = session.exec(
            select(Track.id, Track.release_year).where(
                col(Track.id).in_(track_ids[start : start + _IN_CHUNK])
            )
        ).all()
        for track_id, year in rows:
            if track_id is not None and year is not None:
                years[track_id] = year
    return years


def compute_extended_insights_payload(
    session: Session,
    user: User,
    ctx: AnalyticsContext | None = None,
    *,
    owned_only: bool = True,
) -> dict[str, Any]:
    """The extended survey (I1-I24) over one user's previously-untapped tables.

    Sections mirror their source tables: play_events, saved, feedback, top_items,
    radio, journal, plus a cross_table section. Each carries enough coverage for
    the web to render pending states without a live probe.
    """
    assert user.id is not None
    if ctx is None:
        ctx = AnalyticsContext.load(session, user.id, owned_only=owned_only)

    by_spotify = _playlist_id_by_spotify(session, user.id)
    play_section, playlist_play_counts, play_total = _play_events_section(
        session, user, ctx, by_spotify
    )
    saved_section, total_saves = _saved_section(session, user, ctx)
    feedback_section = _feedback_section(session, user, ctx)
    top_section = _top_items_section(session, user, ctx)
    radio_section = _radio_section(session, user)
    journal_section = _journal_section(session, user)
    cross_section = _cross_table_section(session, ctx, playlist_play_counts)

    # since-crate play count (recent-source only) so the web can offer the range
    # toggle without a second query (per the F2 range contract).
    since_crate_plays = session.exec(
        select(func.count())
        .select_from(PlayEvent)
        .where(PlayEvent.user_id == user.id)
        .where(PlayEvent.source == PlayEventSource.recent)
    ).one()

    return {
        "coverage": {
            "play_events": play_total,
            "since_crate_plays": int(since_crate_plays),
            "total_saved": total_saves,
            "top_snapshots": top_section["snapshot_count"],
        },
        "play_events": play_section,
        "saved": saved_section,
        "feedback": feedback_section,
        "top_items": top_section,
        "radio": radio_section,
        "journal": journal_section,
        "cross_table": cross_section,
    }
