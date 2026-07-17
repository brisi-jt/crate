"""Hand-computed micro-fixtures for every extended-insight metric (I1-I24).

Each assertion is derived from the formula, not from the code's output - the
tests are the specification. Every function is pure (plain dicts / lists), so
these run offline with no session or ORM.
"""

import pytest

from crate.services.insights import metrics_extended as mx

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- I1 play/collect gap


def test_play_collect_gap_diverging_lists() -> None:
    # play counts: t1 heavy, t2 light. collection (membership) counts inverse.
    plays = {1: 20, 2: 2, 3: 5}
    memberships = {1: 1, 2: 4, 3: 2}
    meta = {
        1: {"name": "A", "artist": "x"},
        2: {"name": "B", "artist": "y"},
        3: {"name": "C", "artist": "z"},
    }
    result = mx.play_collect_gap(plays, memberships, meta, top=2)
    # over-played = high plays / low memberships (t1), over-collected = inverse (t2).
    assert result["over_played"][0]["track_id"] == 1
    assert result["over_collected"][0]["track_id"] == 2
    assert result["played_tracks"] == 3


def test_play_collect_gap_empty() -> None:
    result = mx.play_collect_gap({}, {}, {})
    assert result["over_played"] == []
    assert result["over_collected"] == []
    assert result["played_tracks"] == 0


# ---------------------------------------------------------------- I2 listening clock


def test_listening_clock_hour_and_weekday_counts() -> None:
    from datetime import datetime

    # Monday 2024-01-01 09:00, Monday 09:30, Tuesday 14:00.
    plays = [
        datetime(2024, 1, 1, 9, 0),
        datetime(2024, 1, 1, 9, 30),
        datetime(2024, 1, 2, 14, 0),
    ]
    clock = mx.listening_clock(plays)
    assert clock["hours"][9] == 2
    assert clock["hours"][14] == 1
    assert len(clock["hours"]) == 24
    # Monday=0, Tuesday=1.
    assert clock["weekdays"][0] == 2
    assert clock["weekdays"][1] == 1
    assert len(clock["weekdays"]) == 7
    assert clock["total"] == 3
    # peak hour is 9 with 2 plays.
    assert clock["peak_hour"] == 9


def test_listening_clock_empty() -> None:
    clock = mx.listening_clock([])
    assert clock["total"] == 0
    assert clock["peak_hour"] is None
    assert sum(clock["hours"]) == 0


# ---------------------------------------------------------------- I3 rotation velocity


def test_rotation_velocity_recent_vs_deep() -> None:
    # recent adds (< recency_days old) vs deep catalog; plays split.
    # track 1 added recently and played 8x; track 2 added long ago, played 2x.
    recent_track_ids = {1}
    play_counts = {1: 8, 2: 2}
    result = mx.rotation_velocity(play_counts, recent_track_ids)
    # 8 of 10 plays land on recent adds.
    assert result["recent_plays"] == 8
    assert result["deep_plays"] == 2
    assert result["recency_bias"] == pytest.approx(0.8)


def test_rotation_velocity_no_plays() -> None:
    result = mx.rotation_velocity({}, set())
    assert result["recency_bias"] is None


# ---------------------------------------------------------------- I4 context mix


def test_context_mix_shares_by_type() -> None:
    contexts = ["playlist", "playlist", "album", "artist", None]
    mix = mx.context_mix(contexts)
    shares = {entry["context"]: entry for entry in mix["contexts"]}
    assert shares["playlist"]["count"] == 2
    assert shares["playlist"]["share"] == pytest.approx(0.4)
    assert shares["album"]["count"] == 1
    # None becomes "unknown".
    assert shares["unknown"]["count"] == 1
    assert mix["total"] == 5


def test_context_mix_empty() -> None:
    mix = mx.context_mix([])
    assert mix["contexts"] == []
    assert mix["total"] == 0


# ---------------------------------------------------------------- I5 play-mood by hour


def test_play_mood_by_hour_band_means() -> None:
    from datetime import datetime

    # two plays at hour 9 (energy .2/.4 -> mean .3), one at hour 22 (energy .9).
    events = [
        (datetime(2024, 1, 1, 9, 0), {"energy": 0.2, "valence": 0.1}),
        (datetime(2024, 1, 1, 9, 30), {"energy": 0.4, "valence": 0.3}),
        (datetime(2024, 1, 1, 22, 0), {"energy": 0.9, "valence": 0.8}),
    ]
    bands = mx.play_mood_by_hour(events)
    by_band = {b["band"]: b for b in bands["bands"]}
    # morning band (6-12) holds the two hour-9 plays.
    assert by_band["morning"]["count"] == 2
    assert by_band["morning"]["mean_energy"] == pytest.approx(0.3)
    assert by_band["morning"]["mean_valence"] == pytest.approx(0.2)
    # night band (21-24 / 0-6) holds the hour-22 play.
    assert by_band["night"]["count"] == 1
    assert by_band["night"]["mean_energy"] == pytest.approx(0.9)


def test_play_mood_by_hour_empty() -> None:
    bands = mx.play_mood_by_hour([])
    assert all(b["count"] == 0 for b in bands["bands"])
    assert bands["total"] == 0


# ---------------------------------------------------------------- I6 deep cuts vs hits


def test_deep_cuts_vs_hits_by_membership_obscurity() -> None:
    # obscurity = fewer memberships. track 1 in 1 playlist (deep cut),
    # track 3 in 5 playlists (a hit). plays weighted.
    play_counts = {1: 6, 2: 3, 3: 1}
    memberships = {1: 1, 2: 3, 3: 5}
    result = mx.deep_cuts_vs_hits(play_counts, memberships, hit_threshold=4)
    # deep cut = memberships < hit_threshold -> tracks 1,2 (9 plays);
    # hits = memberships >= threshold -> track 3 (1 play).
    assert result["deep_cut_plays"] == 9
    assert result["hit_plays"] == 1
    assert result["deep_cut_share"] == pytest.approx(0.9)


def test_deep_cuts_vs_hits_empty() -> None:
    result = mx.deep_cuts_vs_hits({}, {})
    assert result["deep_cut_share"] is None


# ---------------------------------------------------------------- I22 listened vs neglected


def test_listened_vs_neglected_joins_plays_and_dormancy() -> None:
    # playlist 1: 10 plays, dormant 8 months -> "listened but not curated".
    # playlist 2: 0 plays, dormant 12 months -> "truly neglected".
    play_counts = {1: 10, 2: 0}
    dormancy = {1: (("Alpha", 8)), 2: (("Beta", 12))}
    rows = mx.listened_vs_neglected(play_counts, dormancy)
    by_id = {r["playlist_id"]: r for r in rows}
    assert by_id[1]["plays"] == 10
    assert by_id[1]["months_dormant"] == 8
    assert by_id[2]["plays"] == 0
    assert by_id[2]["months_dormant"] == 12
    # truly-neglected (no plays + dormant) sorts by dormancy; Beta first.
    neglected = [r for r in rows if r["plays"] == 0]
    assert neglected[0]["playlist_id"] == 2


def test_listened_vs_neglected_empty() -> None:
    assert mx.listened_vs_neglected({}, {}) == []
