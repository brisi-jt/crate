"""Pure metrics for the extended insight survey (I1-I24).

These mine the schema the original insights survey never touched: play_events,
saved_tracks, suggestion_feedback, discovery_candidates, top_items_snapshots,
radio_*, and mutation_journal. Like ``metrics.py``, every function here is a
hand-computable transform of plain dicts / lists - no ORM, no session. The
engine loads each table once and feeds these.

Feature inputs, where present, are library percentiles (0..1), never raw
Essentia values. Time inputs are naive/aware datetimes; only their hour and
weekday are read.
"""

from collections import Counter
from itertools import pairwise
from statistics import median
from typing import Any

from crate.services.insights.metrics import FINGERPRINT_FEATURES

__all__ = ["FINGERPRINT_FEATURES"]

# Hour-of-day bands for the play-mood-by-time reading (I5). Bands are chosen so
# each has a clear listening character; night wraps midnight.
HOUR_BANDS: tuple[tuple[str, int, int], ...] = (
    ("morning", 6, 12),
    ("afternoon", 12, 17),
    ("evening", 17, 21),
    ("night", 21, 6),  # wraps: [21,24) + [0,6)
)


def _band_for_hour(hour: int) -> str:
    for name, start, end in HOUR_BANDS:
        if start < end:
            if start <= hour < end:
                return name
        else:  # wrapping band (night)
            if hour >= start or hour < end:
                return name
    return "night"


# ------------------------------------------------------------ I1 play/collect gap


def play_collect_gap(
    play_counts: dict[int, int],
    membership_counts: dict[int, int],
    track_meta: dict[int, dict[str, Any]],
    *,
    top: int = 8,
) -> dict[str, Any]:
    """Tracks you play far more (or less) than your collection weight suggests.

    ``play_counts`` maps track id -> plays; ``membership_counts`` maps track id
    -> how many owned playlists hold it. A track's "gap" is plays scaled against
    its collection footprint: over-played = high plays, low footprint; over-
    collected = filed everywhere but rarely played. Only tracks with at least
    one play are ranked. Returns the two diverging lists plus how many distinct
    tracks were played.
    """
    entries: list[dict[str, Any]] = []
    for track_id, plays in play_counts.items():
        if plays <= 0:
            continue
        memberships = membership_counts.get(track_id, 0)
        meta = track_meta.get(track_id, {})
        # Gap > 0 = played more than filed; < 0 = filed more than played.
        gap = plays - memberships
        entries.append(
            {
                "track_id": track_id,
                "name": meta.get("name", ""),
                "artist": meta.get("artist", ""),
                "plays": plays,
                "memberships": memberships,
                "gap": gap,
            }
        )
    over_played = sorted(entries, key=lambda e: (-e["gap"], -e["plays"], e["track_id"]))
    over_collected = sorted(entries, key=lambda e: (e["gap"], -e["memberships"], e["track_id"]))
    return {
        "over_played": [e for e in over_played if e["gap"] > 0][:top],
        "over_collected": [e for e in over_collected if e["gap"] < 0][:top],
        "played_tracks": len(entries),
    }


# ------------------------------------------------------------ I2 listening clock


def listening_clock(played_at: list[Any]) -> dict[str, Any]:
    """Hour-of-day and day-of-week play histograms (the listening heat strip).

    ``played_at`` is a list of datetimes; only ``.hour`` and ``.weekday()`` are
    read. Returns a 24-length hour histogram, a 7-length weekday histogram
    (Monday=0), the total, and the single busiest hour (None when empty).
    """
    hours = [0] * 24
    weekdays = [0] * 7
    for ts in played_at:
        hours[ts.hour] += 1
        weekdays[ts.weekday()] += 1
    total = len(played_at)
    peak_hour = max(range(24), key=lambda h: hours[h]) if total else None
    return {"hours": hours, "weekdays": weekdays, "total": total, "peak_hour": peak_hour}


# ------------------------------------------------------------ I3 rotation velocity


def rotation_velocity(play_counts: dict[int, int], recent_track_ids: set[int]) -> dict[str, Any]:
    """How much listening lands on recent adds vs the deep catalog (recency bias).

    ``recent_track_ids`` are the tracks added inside the recency window (the
    caller decides the cutoff). ``recency_bias`` is the share of plays that hit
    a recent add - 1.0 = you only spin new arrivals, 0.0 = you live in the
    archive. None when there are no plays.
    """
    recent_plays = sum(count for tid, count in play_counts.items() if tid in recent_track_ids)
    total = sum(play_counts.values())
    deep_plays = total - recent_plays
    recency_bias = round(recent_plays / total, 4) if total else None
    return {
        "recent_plays": recent_plays,
        "deep_plays": deep_plays,
        "total_plays": total,
        "recency_bias": recency_bias,
    }


# ------------------------------------------------------------ I4 context mix


def context_mix(context_types: list[str | None]) -> dict[str, Any]:
    """Where plays come from: playlist vs album vs artist vs show vs unknown.

    ``context_types`` is one entry per play (Spotify's context type, or None
    when it reported none - counted as "unknown"). Returns each observed
    context with its count and share, most common first.
    """
    counts: Counter[str] = Counter(ctx if ctx else "unknown" for ctx in context_types)
    total = len(context_types)
    contexts = [
        {"context": name, "count": count, "share": round(count / total, 4) if total else 0.0}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"contexts": contexts, "total": total}


# ------------------------------------------------------------ I5 play-mood by hour


def play_mood_by_hour(events: list[tuple[Any, dict[str, float]]]) -> dict[str, Any]:
    """Mean energy/valence percentile per hour-band (do you listen calmer at night?).

    ``events`` is (played_at datetime, feature-percentile vector). Each play is
    bucketed into its hour band; bands report play count and mean energy/valence
    percentile (None when the band saw no enriched plays). Bands are always all
    four, in daily order, so the web renders a stable strip.
    """
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for ts, vector in events:
        band = _band_for_hour(ts.hour)
        counts[band] = counts.get(band, 0) + 1
        acc = sums.setdefault(band, {"energy": 0.0, "valence": 0.0})
        acc["energy"] += vector.get("energy", 0.5)
        acc["valence"] += vector.get("valence", 0.5)
    bands = []
    for name, _, _ in HOUR_BANDS:
        n = counts.get(name, 0)
        acc = sums.get(name)
        bands.append(
            {
                "band": name,
                "count": n,
                "mean_energy": round(acc["energy"] / n, 4) if n and acc else None,
                "mean_valence": round(acc["valence"] / n, 4) if n and acc else None,
            }
        )
    return {"bands": bands, "total": len(events)}


# ------------------------------------------------------------ I6 deep cuts vs hits


def deep_cuts_vs_hits(
    play_counts: dict[int, int],
    membership_counts: dict[int, int],
    *,
    hit_threshold: int = 4,
) -> dict[str, Any]:
    """Do you play obscure corners of your library or the well-filed favourites?

    Obscurity is measured within your own collection: a track filed in fewer
    than ``hit_threshold`` owned playlists is a "deep cut"; one filed in that
    many or more is a "hit". Plays are split accordingly. ``deep_cut_share`` =
    share of listening spent on deep cuts (None when there are no plays).
    """
    deep = 0
    hits = 0
    for track_id, plays in play_counts.items():
        if plays <= 0:
            continue
        memberships = membership_counts.get(track_id, 0)
        if memberships >= hit_threshold:
            hits += plays
        else:
            deep += plays
    total = deep + hits
    return {
        "deep_cut_plays": deep,
        "hit_plays": hits,
        "deep_cut_share": round(deep / total, 4) if total else None,
    }


# ------------------------------------------------------------ I22 listened vs neglected


def listened_vs_neglected(
    play_counts: dict[int, int],
    dormancy: dict[int, tuple[str, int]],
) -> list[dict[str, Any]]:
    """Cross of playlist dormancy against how much its tracks are actually played.

    ``play_counts`` maps playlist id -> total plays attributed to that playlist
    (via play context); ``dormancy`` maps playlist id -> (name, months since
    last add/remove). A playlist can be curation-dormant yet heavily played
    (loved but frozen) or dormant AND unplayed (truly neglected). Sorted truly-
    neglected first (no plays, longest dormant), then the rest by dormancy.
    """
    rows = []
    for playlist_id, (name, months) in dormancy.items():
        plays = play_counts.get(playlist_id, 0)
        rows.append(
            {
                "playlist_id": playlist_id,
                "name": name,
                "plays": plays,
                "months_dormant": months,
                "neglected": plays == 0,
            }
        )
    rows.sort(key=lambda r: (not r["neglected"], -r["months_dormant"], r["name"]))
    return rows


# ------------------------------------------------------------ shared: fingerprint deltas


def _mean_fingerprint(vectors: list[dict[str, float]]) -> dict[str, float] | None:
    """Mean percentile per fingerprint feature, or None for an empty set."""
    if not vectors:
        return None
    return {
        feature: sum(v.get(feature, 0.5) for v in vectors) / len(vectors)
        for feature in FINGERPRINT_FEATURES
    }


def _fingerprint_delta(
    left: list[dict[str, float]],
    right: list[dict[str, float]],
    left_key: str,
    right_key: str,
) -> list[dict[str, Any]]:
    """Per-feature (left, right, left-right) rows; empty when either side is empty."""
    left_mean = _mean_fingerprint(left)
    right_mean = _mean_fingerprint(right)
    if left_mean is None or right_mean is None:
        return []
    return [
        {
            "feature": feature,
            left_key: round(left_mean[feature], 4),
            right_key: round(right_mean[feature], 4),
            "delta": round(left_mean[feature] - right_mean[feature], 4),
        }
        for feature in FINGERPRINT_FEATURES
    ]


# ------------------------------------------------------------ I7 liked vs playlist fp


def liked_vs_playlist_fingerprint(
    liked: list[dict[str, float]], playlist: list[dict[str, float]]
) -> dict[str, Any]:
    """Your Liked-Songs sound vs the sound of everything you actually filed.

    Both inputs are percentile vectors; the delta (liked - playlist) says which
    axes your saved-but-unsorted taste leans toward vs your curated library.
    """
    return {
        "axes": _fingerprint_delta(liked, playlist, "liked", "playlist"),
        "liked_count": len(liked),
        "playlist_count": len(playlist),
    }


# ------------------------------------------------------------ I8 save->file latency


def save_file_latency(latencies_days: list[float]) -> dict[str, Any]:
    """How long a track waits between being liked and being filed into a playlist.

    ``latencies_days`` is one entry per filed track (days from saved_at to its
    first playlist add). Returns the median wait and the count. None median when
    nothing has been both saved and filed.
    """
    positive = [d for d in latencies_days if d >= 0]
    return {
        "median_days": round(median(positive), 2) if positive else None,
        "filed_count": len(positive),
    }


# ------------------------------------------------------------ I9 unsave churn


def unsave_churn(*, total_saves: int, removed: int) -> dict[str, Any]:
    """Share of your all-time saves you later un-liked (library churn).

    ``total_saves`` counts every saved_tracks row (active + removed); ``removed``
    counts the un-liked ones. None rate when you've never saved anything.
    """
    return {
        "total_saves": total_saves,
        "removed": removed,
        "churn_rate": round(removed / total_saves, 4) if total_saves else None,
    }


# ------------------------------------------------------------ I10 orphan saves


def orphan_saves(
    *, saved_ids: set[int], filed_ids: set[int], track_meta: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Liked tracks that live in no owned playlist - the inbox you forgot.

    ``saved_ids`` are active Liked-Songs track ids; ``filed_ids`` are track ids
    present in at least one owned playlist. Orphans are saved-but-unfiled.
    """
    orphan_ids = saved_ids - filed_ids
    orphans = [
        {
            "track_id": tid,
            "name": track_meta.get(tid, {}).get("name", ""),
            "artist": track_meta.get(tid, {}).get("artist", ""),
        }
        for tid in sorted(orphan_ids)
    ]
    return {
        "orphans": orphans,
        "orphan_count": len(orphan_ids),
        "saved_count": len(saved_ids),
    }


# ------------------------------------------------------------ I11 source efficacy


def source_efficacy(tallies: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    """Accept rate per discovery source - which pipeline earns its suggestions.

    ``tallies`` maps source name -> {"accept", "reject", "skip"} counts. Accept
    rate = accepts / reviewed (accept+reject; skips aren't a verdict). Sorted
    best acceptance first.
    """
    board = []
    for source, counts in tallies.items():
        accept = counts.get("accept", 0)
        reject = counts.get("reject", 0)
        reviewed = accept + reject
        board.append(
            {
                "source": source,
                "accept": accept,
                "reject": reject,
                "skip": counts.get("skip", 0),
                "reviewed": reviewed,
                "accept_rate": round(accept / reviewed, 4) if reviewed else 0.0,
            }
        )
    board.sort(key=lambda e: (-e["accept_rate"], -e["reviewed"], e["source"]))
    return board


# ------------------------------------------------------------ I12 taste of yes


def taste_of_yes(
    accepted: list[dict[str, float]], rejected: list[dict[str, float]]
) -> dict[str, Any]:
    """The acoustic signature of your yes vs your no on suggested tracks.

    Percentile vectors of accepted and rejected candidates; the per-axis means
    show which sonic qualities you reach for (and which you turn down).
    """
    return {
        "axes": _fingerprint_delta(accepted, rejected, "accepted", "rejected"),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }


# ------------------------------------------------------------ I13 per-artist affinity


def per_artist_affinity(
    tallies: dict[str, dict[str, int]], *, top: int = 8, min_reviews: int = 2
) -> dict[str, Any]:
    """Artists you consistently accept vs consistently reject on the suggestion queue.

    ``tallies`` maps artist -> {"accept", "reject"}. Only artists with at least
    ``min_reviews`` decisions are ranked (avoids one-off noise). Returns the most
    loved and most disliked, by accept rate.
    """
    entries = []
    for artist, counts in tallies.items():
        accept = counts.get("accept", 0)
        reject = counts.get("reject", 0)
        reviews = accept + reject
        if reviews < min_reviews:
            continue
        entries.append(
            {
                "artist": artist,
                "accept": accept,
                "reject": reject,
                "reviews": reviews,
                "accept_rate": round(accept / reviews, 4),
            }
        )
    loved = sorted(entries, key=lambda e: (-e["accept_rate"], -e["reviews"], e["artist"]))
    disliked = sorted(entries, key=lambda e: (e["accept_rate"], -e["reviews"], e["artist"]))
    return {
        "loved": [e for e in loved if e["accept_rate"] > 0.5][:top],
        "disliked": [e for e in disliked if e["accept_rate"] < 0.5][:top],
    }


# ------------------------------------------------------------ I14 candidate funnel


# The discovery lifecycle stages, in flow order.
_FUNNEL_STAGES = ("pending", "resolved", "unresolvable", "accepted", "rejected")


def candidate_funnel(status_counts: dict[str, int]) -> dict[str, Any]:
    """Discovery candidates by lifecycle stage - the proposal-to-decision funnel.

    ``status_counts`` maps CandidateStatus value -> count. Stages are reported in
    flow order (pending -> resolved -> accepted/rejected) so the web draws a
    funnel; missing stages read zero.
    """
    stages = [{"stage": stage, "count": status_counts.get(stage, 0)} for stage in _FUNNEL_STAGES]
    return {"stages": stages, "total": sum(status_counts.values())}


# ------------------------------------------------------------ I15 top vs library


def top_items_sound(top: list[dict[str, float]], library: list[dict[str, float]]) -> dict[str, Any]:
    """How your Spotify-affinity top tracks sound vs your whole library.

    ``top`` are percentile vectors of tracks in the latest top-items snapshot
    (resolved into the catalog); ``library`` is every enriched owned track. The
    delta (top - library) shows where your active listening pulls away from your
    collection's centre.
    """
    return {
        "axes": _fingerprint_delta(top, library, "top", "library"),
        "top_count": len(top),
        "library_count": len(library),
    }


# ------------------------------------------------------------ I16 affinity churn


def affinity_churn(snapshots: list[list[str]]) -> dict[str, Any]:
    """How much your top-items set turns over between successive captures.

    ``snapshots`` is an ordered (oldest first) list of ranked-id lists for one
    (kind, range). Each transition reports the Jaccard overlap of consecutive
    sets - 1.0 = identical, 0.0 = complete turnover. Needs 2+ snapshots.
    """
    transitions = []
    for older, newer in pairwise(snapshots):
        a, b = set(older), set(newer)
        union = a | b
        jaccard = len(a & b) / len(union) if union else 1.0
        transitions.append({"jaccard": round(jaccard, 4)})
    mean_jaccard = (
        round(sum(t["jaccard"] for t in transitions) / len(transitions), 4) if transitions else None
    )
    return {"transitions": transitions, "mean_jaccard": mean_jaccard}


# ------------------------------------------------------------ I17 short vs long


def short_vs_long_divergence(*, short: list[str], long: list[str]) -> dict[str, Any]:
    """Current obsessions vs settled favourites (short-term vs long-term top items).

    ``short`` and ``long`` are ranked id lists for the short (~4wk) and long
    (~1yr) affinity windows. rising = in short only (new obsessions), fading =
    in long only (cooling), stable = in both.
    """
    short_set, long_set = set(short), set(long)
    return {
        "rising": sorted(short_set - long_set),
        "fading": sorted(long_set - short_set),
        "stable": sorted(short_set & long_set),
        "short_count": len(short_set),
        "long_count": len(long_set),
    }


# ------------------------------------------------------------ I18 radio keep rate


def radio_keep_rate(per_seed: dict[str, dict[str, int]]) -> dict[str, Any]:
    """How often you keep vs skip radio items, overall and by seed kind.

    ``per_seed`` maps seed kind -> {"kept", "skipped"}. Keep rate = kept /
    (kept+skipped) - the fraction of a session you actually held onto. None
    overall rate when no radio item has been judged.
    """
    total_kept = sum(c.get("kept", 0) for c in per_seed.values())
    total_skipped = sum(c.get("skipped", 0) for c in per_seed.values())
    judged = total_kept + total_skipped
    by_seed = []
    for seed, counts in per_seed.items():
        kept = counts.get("kept", 0)
        skipped = counts.get("skipped", 0)
        seed_judged = kept + skipped
        by_seed.append(
            {
                "seed_kind": seed,
                "kept": kept,
                "skipped": skipped,
                "keep_rate": round(kept / seed_judged, 4) if seed_judged else None,
            }
        )
    by_seed.sort(key=lambda e: (-(e["keep_rate"] or 0), e["seed_kind"]))
    return {
        "kept": total_kept,
        "skipped": total_skipped,
        "total": judged,
        "keep_rate": round(total_kept / judged, 4) if judged else None,
        "by_seed": by_seed,
    }


# ------------------------------------------------------------ I19 discovery conversion


def discovery_conversion(*, discovery_total: int, discovery_kept: int) -> dict[str, Any]:
    """Share of interleaved discovery items you kept - radio's conversion rate.

    ``discovery_total`` counts radio items that were discovery candidates;
    ``discovery_kept`` counts the ones you kept. None rate when radio has served
    no discovery items.
    """
    return {
        "discovery_total": discovery_total,
        "kept": discovery_kept,
        "conversion_rate": round(discovery_kept / discovery_total, 4) if discovery_total else None,
    }


# ------------------------------------------------------------ I20 curation intensity


def curation_intensity(
    op_counts: dict[str, int], *, undone: int, total: int, weeks: float
) -> dict[str, Any]:
    """Your editing tempo: op mix, edits per week, and how often you undo.

    ``op_counts`` maps journal op type -> count; ``undone`` is how many entries
    were reversed; ``total`` is all journal entries; ``weeks`` is the span the
    journal covers. None rates when there's no history / no elapsed time.
    """
    op_mix = [
        {"op_type": op, "count": count}
        for op, count in sorted(op_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "op_mix": op_mix,
        "total": total,
        "undone": undone,
        "undo_rate": round(undone / total, 4) if total else None,
        "edits_per_week": round(total / weeks, 2) if weeks > 0 else None,
    }


# ------------------------------------------------------------ I21 bulk-algebra usage


def bulk_algebra_usage(op_counts: dict[str, int]) -> dict[str, Any]:
    """Which set operations you reach for in bulk ops (union / difference / ...).

    ``op_counts`` maps BulkOperation value -> how many times you applied it.
    Sorted most-used first.
    """
    operations = [
        {"operation": op, "count": count}
        for op, count in sorted(op_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"operations": operations, "total": sum(op_counts.values())}


# ------------------------------------------------------------ I23 calibration drift


def calibration_drift(series: list[dict[str, Any]]) -> dict[str, Any]:
    """How each feature's p10-p90 spread has moved over calibration snapshots.

    ``series`` is a flat list of {"captured_at", "feature", "p10", "p90"} points.
    Grouped per feature (in fingerprint order), each point carries its spread
    (p90-p10); ``spread_delta`` is newest minus oldest - positive = the library's
    taste for that axis is widening.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for point in series:
        feature = point["feature"]
        spread = round(point["p90"] - point["p10"], 4)
        grouped.setdefault(feature, []).append(
            {"captured_at": point["captured_at"], "spread": spread}
        )
    features = []
    for feature in FINGERPRINT_FEATURES:
        points = grouped.get(feature)
        if not points:
            continue
        points.sort(key=lambda p: p["captured_at"])
        spread_delta = round(points[-1]["spread"] - points[0]["spread"], 4)
        features.append({"feature": feature, "points": points, "spread_delta": spread_delta})
    return {"features": features}


# ------------------------------------------------------------ I24 era of add vs release


def era_add_vs_release(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    """Nostalgia waves: when you add tracks vs when those tracks were released.

    ``pairs`` are (add_year, release_year) per filed track. Grouped by add year,
    each reports the median gap (add - release) - a big gap is a nostalgia dig,
    near-zero is chasing new releases.
    """
    by_add: dict[int, list[int]] = {}
    for add_year, release_year in pairs:
        by_add.setdefault(add_year, []).append(add_year - release_year)
    add_years = [
        {
            "add_year": year,
            "count": len(gaps),
            "median_gap_years": round(median(gaps), 1),
        }
        for year, gaps in sorted(by_add.items())
    ]
    return {"add_years": add_years, "total": len(pairs)}
