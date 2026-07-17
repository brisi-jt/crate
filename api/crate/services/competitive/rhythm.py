"""F1 — the listening-rhythm dashboard's aggregations.

stats.fm and volt.fm charge for exactly these numbers: when you listen (clocks),
how much (plays + minutes), how consistently (streaks), and what (top plays).
crate already captures the events, so F1 is aggregation. The hour/weekday
strips reuse the I2 ``listening_clock`` primitive verbatim so the survey and the
dashboard read the same clock.

Every figure is a pure transform of a list of play dicts
(``{track_id, played_at, ms_played}``); the ORM read and the all_time /
since_crate range filter live in the engine (the range param the GDPR-import
work already defined on ``/v1/listening/recent``).
"""

from collections import Counter
from itertools import pairwise
from typing import Any

from crate.services.insights.metrics_extended import listening_clock

# Nominal track length used to estimate minutes when a play has no recorded
# duration. Live recently-played captures don't carry ms_played; GDPR imports
# do. 3.5 minutes is a reasonable pop/rock mean — the report flags any total
# that leans on this estimate so the number is never presented as exact.
NOMINAL_TRACK_MS = 210_000


def minutes_listened(plays: list[dict[str, Any]]) -> dict[str, Any]:
    """Total minutes listened, exact where ``ms_played`` is present.

    Returns the minutes and whether any play fell back to the nominal-length
    estimate (``estimated`` True the moment one play lacks a duration).
    """
    total_ms = 0
    estimated = False
    for play in plays:
        ms = play.get("ms_played")
        if ms is None:
            ms = NOMINAL_TRACK_MS
            estimated = True
        total_ms += ms
    return {"minutes": round(total_ms / 60_000, 1), "estimated": estimated}


def listening_streaks(played_at: list[Any]) -> dict[str, Any]:
    """Longest and current run of consecutive calendar days with a play.

    ``played_at`` is a list of datetimes; only the date is read. Multiple plays
    on one day count once. ``current`` is the streak ending on the most recent
    listening day.
    """
    days = sorted({ts.date() for ts in played_at})
    if not days:
        return {"longest": 0, "current": 0}

    longest = current = 1
    for prev, day in pairwise(days):
        if (day - prev).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
    return {"longest": longest, "current": current}


# How many top-played tracks the dashboard lists.
TOP_PLAYED = 12


def rhythm_report(
    plays: list[dict[str, Any]],
    track_meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """The full dashboard payload: counts, clock (I2), minutes, streaks, top plays."""
    played_at = [p["played_at"] for p in plays]
    play_counts: Counter[int] = Counter(p["track_id"] for p in plays)

    top_played = [
        {
            "track_id": track_id,
            "plays": count,
            "name": track_meta.get(track_id, {}).get("name", ""),
            "artist": track_meta.get(track_id, {}).get("artist", ""),
        }
        for track_id, count in sorted(play_counts.items(), key=lambda kv: (-kv[1], kv[0]))[
            :TOP_PLAYED
        ]
    ]

    return {
        "total_plays": len(plays),
        "distinct_tracks": len(play_counts),
        "clock": listening_clock(played_at),
        "minutes": minutes_listened(plays),
        "streaks": listening_streaks(played_at),
        "top_played": top_played,
    }
