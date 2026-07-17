"""Pin candidate pool for the insights surface (P1 api half).

The deterministic pins in ``pins.py`` repeat because they rank a tiny fixed set
and keep the top few. P1 fixes that by shipping a *wide* candidate pool (target
15-25) tagged by family, and letting the client sample it: max one pin per
family per refresh, a session-seeded weighted shuffle, and down-weighting of
recently-shown ids. This module builds the pool; the sampler is web-side.

Every candidate carries:
  - family        : the insight family (max-1-per-family quota key)
  - metric_ref    : the glossary key the web attaches an explain to
  - line          : the field-manual annotation
  - dismissible_id: stable id for dismissal memory + recently-shown weighting
  - salience      : 0..1 ranking weight (the shuffle's weight source)

A candidate is only emitted when its underlying reading is non-trivial, so a
thin library yields a small (or empty) pool rather than filler.
"""

from typing import Any

# The extended-insight families a candidate can belong to. The client enforces
# at most one pin per family per refresh, so this list bounds pool diversity.
FAMILIES: tuple[str, ...] = (
    "play_events",
    "saved",
    "feedback",
    "top_items",
    "radio",
    "journal",
    "cross_table",
)


def _candidate(
    family: str, metric_ref: str, anchor: str, line: str, salience: float
) -> dict[str, Any]:
    return {
        "family": family,
        "category": family,
        "metric_ref": metric_ref,
        "anchor": anchor,
        "line": line,
        "dismissible_id": f"insights:{family}:{anchor}:{metric_ref}",
        "salience": round(max(0.0, min(1.0, salience)), 4),
    }


def _pct(value: float | None) -> int:
    return round((value or 0.0) * 100)


def insights_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """A wide, family-tagged candidate pool over the extended-insights payload.

    Draws one or more candidates from each family whose reading is meaningful.
    Returns 0..N candidates (target 15-25 on a populated library); the client
    samples this down under family quotas and anti-repeat weighting.
    """
    pins: list[dict[str, Any]] = []
    play = payload.get("play_events", {})
    saved = payload.get("saved", {})
    feedback = payload.get("feedback", {})
    top = payload.get("top_items", {})
    radio = payload.get("radio", {})
    journal = payload.get("journal", {})
    cross = payload.get("cross_table", {})

    # -- play_events -------------------------------------------------------
    gap = play.get("play_collect_gap", {})
    for entry in gap.get("over_played", [])[:2]:
        pins.append(
            _candidate(
                "play_events",
                "play_collect_gap",
                f"over_played:{entry['track_id']}",
                f"You spin {entry['name']} far more than you've filed it "
                f"({entry['plays']} plays, in {entry['memberships']} playlists).",
                salience=min(1.0, entry["plays"] / 25.0),
            )
        )
    for entry in gap.get("over_collected", [])[:1]:
        pins.append(
            _candidate(
                "play_events",
                "play_collect_gap",
                f"over_collected:{entry['track_id']}",
                f"{entry['name']} is filed in {entry['memberships']} playlists but barely played.",
                salience=min(1.0, entry["memberships"] / 8.0),
            )
        )
    clock = play.get("listening_clock", {})
    if clock.get("total") and clock.get("peak_hour") is not None:
        pins.append(
            _candidate(
                "play_events",
                "listening_clock",
                f"peak_hour:{clock['peak_hour']}",
                f"Your listening peaks around {clock['peak_hour']:02d}:00.",
                salience=0.5,
            )
        )
    rotation = play.get("rotation_velocity", {})
    if rotation.get("recency_bias") is not None:
        bias = rotation["recency_bias"]
        lean = "new arrivals" if bias >= 0.5 else "the deep catalog"
        pins.append(
            _candidate(
                "play_events",
                "rotation_velocity",
                "recency_bias",
                f"{_pct(bias)}% of your plays land on {lean}.",
                salience=abs(bias - 0.5) * 2,
            )
        )
    ctx = play.get("context_mix", {})
    contexts = ctx.get("contexts", [])
    if contexts and ctx.get("total"):
        top_ctx = contexts[0]
        pins.append(
            _candidate(
                "play_events",
                "context_mix",
                f"context:{top_ctx['context']}",
                f"{_pct(top_ctx['share'])}% of your plays come from {top_ctx['context']}s.",
                salience=top_ctx["share"],
            )
        )
    deep = play.get("deep_cuts_vs_hits", {})
    if deep.get("deep_cut_share") is not None:
        share = deep["deep_cut_share"]
        pins.append(
            _candidate(
                "play_events",
                "deep_cuts_vs_hits",
                "deep_cut_share",
                f"{_pct(share)}% of your listening is deep cuts, not well-filed hits.",
                salience=abs(share - 0.5) * 2,
            )
        )

    # -- saved -------------------------------------------------------------
    orphans = saved.get("orphan_saves", {})
    if orphans.get("orphan_count"):
        pins.append(
            _candidate(
                "saved",
                "orphan_saves",
                "orphans",
                f"{orphans['orphan_count']} liked tracks sit in no playlist — an inbox you forgot.",
                salience=min(1.0, orphans["orphan_count"] / 25.0),
            )
        )
    latency = saved.get("save_file_latency", {})
    if latency.get("median_days") is not None and latency.get("filed_count"):
        pins.append(
            _candidate(
                "saved",
                "save_file_latency",
                "median_days",
                f"You typically file a liked track {latency['median_days']:.0f} days "
                f"after saving it.",
                salience=0.4,
            )
        )
    churn = saved.get("unsave_churn", {})
    if churn.get("churn_rate") is not None and churn.get("total_saves"):
        pins.append(
            _candidate(
                "saved",
                "unsave_churn",
                "churn_rate",
                f"You've later un-liked {_pct(churn['churn_rate'])}% of everything you ever saved.",
                salience=churn["churn_rate"],
            )
        )

    # -- feedback ----------------------------------------------------------
    efficacy = feedback.get("source_efficacy", [])
    if efficacy:
        best = efficacy[0]
        if best.get("reviewed"):
            pins.append(
                _candidate(
                    "feedback",
                    "source_efficacy",
                    f"source:{best['source']}",
                    f"You accept {_pct(best['accept_rate'])}% of {best['source']} "
                    f"suggestions — its best-earning source.",
                    salience=best["accept_rate"],
                )
            )
    affinity = feedback.get("per_artist_affinity", {})
    for entry in affinity.get("loved", [])[:1]:
        pins.append(
            _candidate(
                "feedback",
                "per_artist_affinity",
                f"loved:{entry['artist']}",
                f"You've accepted every {entry['artist']} suggestion so far.",
                salience=min(1.0, entry["reviews"] / 6.0),
            )
        )
    for entry in affinity.get("disliked", [])[:1]:
        pins.append(
            _candidate(
                "feedback",
                "per_artist_affinity",
                f"disliked:{entry['artist']}",
                f"You keep turning down {entry['artist']} suggestions.",
                salience=min(1.0, entry["reviews"] / 6.0),
            )
        )

    # -- top_items ---------------------------------------------------------
    short_long = top.get("short_vs_long", {})
    rising = short_long.get("rising", [])
    if rising:
        pins.append(
            _candidate(
                "top_items",
                "short_vs_long",
                "rising",
                f"{len(rising)} new obsessions have entered your recent rotation.",
                salience=min(1.0, len(rising) / 10.0),
            )
        )
    churn_top = top.get("affinity_churn", {})
    if churn_top.get("mean_jaccard") is not None:
        stability = churn_top["mean_jaccard"]
        pins.append(
            _candidate(
                "top_items",
                "affinity_churn",
                "mean_jaccard",
                f"Your top artists hold {_pct(stability)}% steady between captures.",
                salience=abs(stability - 0.5) * 2,
            )
        )

    # -- radio -------------------------------------------------------------
    keep = radio.get("keep_rate", {})
    if keep.get("keep_rate") is not None and keep.get("total"):
        pins.append(
            _candidate(
                "radio",
                "radio_keep_rate",
                "keep_rate",
                f"You keep {_pct(keep['keep_rate'])}% of what radio plays you.",
                salience=keep["keep_rate"],
            )
        )
    conversion = radio.get("discovery_conversion", {})
    if conversion.get("conversion_rate") is not None and conversion.get("discovery_total"):
        pins.append(
            _candidate(
                "radio",
                "discovery_conversion",
                "conversion_rate",
                f"{_pct(conversion['conversion_rate'])}% of radio's discovery picks earn a keep.",
                salience=conversion["conversion_rate"],
            )
        )

    # -- journal -----------------------------------------------------------
    intensity = journal.get("curation_intensity", {})
    if intensity.get("edits_per_week") is not None:
        pins.append(
            _candidate(
                "journal",
                "curation_intensity",
                "edits_per_week",
                f"You make about {intensity['edits_per_week']:.0f} curation edits a week.",
                salience=min(1.0, intensity["edits_per_week"] / 20.0),
            )
        )
    if intensity.get("undo_rate") is not None and intensity.get("total"):
        pins.append(
            _candidate(
                "journal",
                "curation_intensity",
                "undo_rate",
                f"You undo {_pct(intensity['undo_rate'])}% of your edits.",
                salience=intensity["undo_rate"],
            )
        )
    bulk = journal.get("bulk_algebra", {})
    if bulk.get("total"):
        ops = bulk.get("operations", [])
        if ops:
            pins.append(
                _candidate(
                    "journal",
                    "bulk_algebra",
                    f"operation:{ops[0]['operation']}",
                    f"Your go-to bulk operation is {ops[0]['operation']} "
                    f"(used {ops[0]['count']} times).",
                    salience=min(1.0, ops[0]["count"] / 10.0),
                )
            )

    # -- cross_table -------------------------------------------------------
    neglected = cross.get("listened_vs_neglected", [])
    for entry in neglected[:1]:
        if entry.get("plays") == 0 and entry.get("months_dormant", 0) >= 6:
            pins.append(
                _candidate(
                    "cross_table",
                    "listened_vs_neglected",
                    f"playlist:{entry['playlist_id']}",
                    f"{entry['name']} is untouched and unplayed for "
                    f"{entry['months_dormant']} months.",
                    salience=min(1.0, entry["months_dormant"] / 24.0),
                )
            )
    era = cross.get("era_add_vs_release", {})
    for entry in era.get("add_years", [])[-1:]:
        if entry.get("median_gap_years", 0) >= 5:
            pins.append(
                _candidate(
                    "cross_table",
                    "era_add_vs_release",
                    f"add_year:{entry['add_year']}",
                    f"Tracks you added in {entry['add_year']} were, on median, "
                    f"{entry['median_gap_years']:.0f} years old — a nostalgia dig.",
                    salience=min(1.0, entry["median_gap_years"] / 30.0),
                )
            )

    return pins
