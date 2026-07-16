"""Control-character sanitization of externally-sourced names.

A raw control character in a track/artist/playlist name breaks strict JSON
consumers downstream. These pin that names are scrubbed at the ingest write
path (the durable fix) and cover the shared helper directly.
"""

import json

import pytest
from sqlmodel import Session, select

from crate.model.orm import Artist, Track, User
from crate.services.sync import upsert_artist, upsert_track
from crate.services.text import clean_name, clean_optional_name

pytestmark = pytest.mark.unit


def test_clean_name_strips_control_chars() -> None:
    assert clean_name("Bad\x01Name") == "BadName"
    assert clean_name("with\ttab\nand\x00null") == "withtabandnull"


def test_clean_name_is_idempotent() -> None:
    once = clean_name("Bad\x1fName")
    assert clean_name(once) == once == "BadName"


def test_clean_name_leaves_normal_names_untouched() -> None:
    assert clean_name("Café del Mar — 1812 Overture") == "Café del Mar — 1812 Overture"


def test_clean_optional_name_passes_through_none() -> None:
    assert clean_optional_name(None) is None


class _SpotifyArtist:
    def __init__(self, id_: str, name: str) -> None:
        self.id = id_
        self.name = name


class _ExternalIds:
    isrc = None


class _SpotifyTrack:
    def __init__(self, id_: str, name: str, artist_name: str) -> None:
        self.id = id_
        self.name = name
        self.artists = [_SpotifyArtist("art-1", artist_name)]
        self.external_ids = _ExternalIds()
        self.album = None
        self.duration_ms = 1000


def test_upsert_track_scrubs_control_chars_from_names(session: Session, user: User) -> None:
    remote = _SpotifyTrack("sp-1", "Track\x07Bell", "Artist\x1bEsc")

    upsert_track(session, remote)  # type: ignore[arg-type]

    track = session.exec(select(Track).where(Track.spotify_id == "sp-1")).one()
    assert track.name == "TrackBell"
    # The denormalized artists JSON blob is scrubbed too — it re-serializes into
    # every track response.
    assert track.artists[0]["name"] == "ArtistEsc"
    artist = session.exec(select(Artist).where(Artist.spotify_id == "art-1")).one()
    assert artist.name == "ArtistEsc"

    # The whole track row round-trips through strict JSON without a control char.
    payload = json.dumps({"name": track.name, "artists": track.artists})
    reparsed = json.loads(payload)
    assert reparsed["name"] == "TrackBell"


def test_upsert_artist_scrubs_control_chars(session: Session) -> None:
    upsert_artist(session, "art-2", "Na\x00me")
    artist = session.exec(select(Artist).where(Artist.spotify_id == "art-2")).one()
    assert artist.name == "Name"


def test_safe_json_response_survives_a_lone_surrogate() -> None:
    # Belt-and-suspenders: a name corrupted before the ingest fix landed (a lone
    # surrogate) must not break the response body. The default serializer would
    # raise UnicodeEncodeError; SafeJSONResponse encodes with replacement so the
    # body always parses.
    from crate.errors import SafeJSONResponse

    body = SafeJSONResponse(content={"name": "Bad\ud83dName", "ok": "café"}).body
    reparsed = json.loads(body)
    assert reparsed["ok"] == "café"
    assert "Bad" in reparsed["name"] and "Name" in reparsed["name"]


def _load_scrub_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "scrub_control_chars.py"
    spec = importlib.util.spec_from_file_location("scrub_control_chars", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scrub_script_is_run_twice_safe(session: Session, user: User) -> None:
    from crate.model.orm import Playlist

    # Seed corrupt rows directly (bypassing the now-scrubbing ingest path).
    session.add(Track(spotify_id="t1", name="Dir\x01ty", artists=[{"name": "Ar\x02t"}]))
    session.add(Artist(spotify_id="a1", name="Ba\x03d"))
    session.add(Playlist(user_id=user.id, spotify_id="p1", name="Mi\x04x", snapshot_id="s"))
    session.commit()

    module = _load_scrub_module()

    first = module.scrub(session, dry_run=False)
    assert first == {"tracks": 1, "artists": 1, "playlists": 1}

    track = session.exec(select(Track).where(Track.spotify_id == "t1")).one()
    assert track.name == "Dirty"
    assert track.artists[0]["name"] == "Art"

    # Second run finds nothing left to scrub.
    second = module.scrub(session, dry_run=False)
    assert second == {"tracks": 0, "artists": 0, "playlists": 0}
