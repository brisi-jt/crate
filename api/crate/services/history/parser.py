"""Parse a Spotify "extended streaming history" export into play records.

The export (requested from Spotify's privacy page, delivered weeks later) is a
set of ``Streaming_History_Audio_*.json`` files, each a JSON array of records.
The fields this parser reads:

    ts                              ISO-8601 UTC end-of-play timestamp
    ms_played                       milliseconds listened
    spotify_track_uri               "spotify:track:<id>" (null for podcasts)
    master_metadata_track_name      track name (null for podcasts)
    master_metadata_album_artist_name
    master_metadata_album_album_name

Everything else (platform, conn_country, reason_*, shuffle, skipped, offline,
incognito_mode, the episode_* fields) is carried verbatim into the review
payload but not otherwise used.

Parsing is pure and offline: it turns records into ``HistoryPlay`` values and
records why any line was dropped, without touching the database or Spotify.
Ingestion (dedupe, track resolution, review parking) is the caller's job.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# A track uri looks like "spotify:track:<base62 id>". Podcast episodes carry a
# "spotify:episode:" uri instead, and local files "spotify:local:...".
_TRACK_URI_PREFIX = "spotify:track:"


@dataclass(frozen=True)
class HistoryPlay:
    """One resolved-to-a-uri listen from the export, ready for ingestion."""

    spotify_id: str
    played_at: datetime
    ms_played: int
    content_key: str
    track_name: str | None
    artist_name: str | None
    album_name: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class SkippedRecord:
    """A line that carried no ingestible play, with the reason it was dropped."""

    reason: str
    raw: dict[str, Any]


@dataclass
class ParsedHistory:
    """The outcome of parsing one or more export files."""

    plays: list[HistoryPlay] = field(default_factory=list)
    skipped: list[SkippedRecord] = field(default_factory=list)


def _parse_ts(value: Any) -> datetime | None:
    """Naive-UTC datetime from an export ``ts`` string, or None if unusable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # ts is always UTC; MySQL DATETIME columns are naive UTC (model.orm.base.utcnow).
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def content_key(played_at_raw: Any, track_uri: Any) -> str:
    """Stable dedupe key for a source line: its raw ts + track uri."""
    basis = f"{played_at_raw}|{track_uri}"
    return hashlib.sha1(basis.encode()).hexdigest()


def parse_history_records(records: list[dict[str, Any]]) -> ParsedHistory:
    """Turn raw export records into plays + a reasoned list of skips.

    Skip reasons: ``no_track_uri`` (podcast/no uri), ``non_track_uri`` (local
    file or episode uri), ``zero_ms_played`` (never actually listened),
    ``bad_timestamp`` (missing/unparseable ts). Duplicate (ts, uri) lines
    within the input collapse to a single play.
    """
    result = ParsedHistory()
    seen_keys: set[str] = set()

    for record in records:
        ts_raw = record.get("ts")
        played_at = _parse_ts(ts_raw)
        if played_at is None:
            result.skipped.append(SkippedRecord("bad_timestamp", record))
            continue

        uri = record.get("spotify_track_uri")
        if uri is None:
            result.skipped.append(SkippedRecord("no_track_uri", record))
            continue
        if not isinstance(uri, str) or not uri.startswith(_TRACK_URI_PREFIX):
            result.skipped.append(SkippedRecord("non_track_uri", record))
            continue

        ms_played_raw = record.get("ms_played")
        ms_played = ms_played_raw if isinstance(ms_played_raw, int) else 0
        if ms_played <= 0:
            result.skipped.append(SkippedRecord("zero_ms_played", record))
            continue

        key = content_key(ts_raw, uri)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        result.plays.append(
            HistoryPlay(
                spotify_id=uri[len(_TRACK_URI_PREFIX) :],
                played_at=played_at,
                ms_played=ms_played,
                content_key=key,
                track_name=record.get("master_metadata_track_name"),
                artist_name=record.get("master_metadata_album_artist_name"),
                album_name=record.get("master_metadata_album_album_name"),
                raw=record,
            )
        )

    return result
