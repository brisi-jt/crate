"""Spotify extended-streaming-history parser — the real export shape + edges."""

from datetime import datetime

import pytest

from crate.services.history.parser import ParsedHistory, parse_history_records

pytestmark = pytest.mark.unit


def audio_record(**overrides: object) -> dict[str, object]:
    """A well-formed music record in the real Streaming_History_Audio shape."""
    record: dict[str, object] = {
        "ts": "2021-06-30T22:34:47Z",
        "platform": "osx",
        "ms_played": 210_000,
        "conn_country": "GB",
        "master_metadata_track_name": "Communication Breakdown",
        "master_metadata_album_artist_name": "Led Zeppelin",
        "master_metadata_album_album_name": "Led Zeppelin",
        "spotify_track_uri": "spotify:track:2whQxHDxButA5STZ32FYme",
        "episode_name": None,
        "episode_show_name": None,
        "spotify_episode_uri": None,
        "reason_start": "clickrow",
        "reason_end": "endplay",
        "shuffle": False,
        "skipped": False,
        "offline": False,
        "incognito_mode": False,
    }
    record.update(overrides)
    return record


def test_parses_a_music_record() -> None:
    result = parse_history_records([audio_record()])

    assert isinstance(result, ParsedHistory)
    assert len(result.plays) == 1
    play = result.plays[0]
    assert play.spotify_id == "2whQxHDxButA5STZ32FYme"
    assert play.played_at == datetime(2021, 6, 30, 22, 34, 47)
    assert play.ms_played == 210_000
    assert play.track_name == "Communication Breakdown"
    assert play.artist_name == "Led Zeppelin"


def test_podcast_episode_has_no_track_uri_and_is_skipped() -> None:
    episode = audio_record(
        spotify_track_uri=None,
        master_metadata_track_name=None,
        master_metadata_album_artist_name=None,
        episode_name="Some Episode",
        episode_show_name="Some Show",
        spotify_episode_uri="spotify:episode:abc123",
    )

    result = parse_history_records([episode])

    assert result.plays == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "no_track_uri"


def test_zero_ms_played_is_dropped_as_a_non_listen() -> None:
    result = parse_history_records([audio_record(ms_played=0)])

    assert result.plays == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "zero_ms_played"


def test_local_file_uri_is_skipped() -> None:
    local = audio_record(spotify_track_uri="spotify:local:Artist:Album:Track:200")

    result = parse_history_records([local])

    assert result.plays == []
    assert result.skipped[0].reason == "non_track_uri"


def test_missing_or_malformed_ts_is_skipped_not_crashed() -> None:
    result = parse_history_records([audio_record(ts=None), audio_record(ts="not-a-date")])

    assert result.plays == []
    assert {s.reason for s in result.skipped} == {"bad_timestamp"}


def test_duplicate_records_in_one_file_are_collapsed() -> None:
    # Same ts + uri twice in the export → one play (the export can repeat).
    result = parse_history_records([audio_record(), audio_record()])

    assert len(result.plays) == 1


def test_content_key_is_stable_and_distinct_per_ts_and_track() -> None:
    a = parse_history_records([audio_record()]).plays[0]
    b = parse_history_records([audio_record(spotify_track_uri="spotify:track:other")]).plays[0]
    c = parse_history_records([audio_record(ts="2021-07-01T00:00:00Z")]).plays[0]

    assert a.content_key == parse_history_records([audio_record()]).plays[0].content_key
    assert a.content_key != b.content_key
    assert a.content_key != c.content_key


def test_offline_timestamp_null_is_tolerated() -> None:
    result = parse_history_records([audio_record(offline_timestamp=None)])
    assert len(result.plays) == 1
