"""MySQL-backed response cache used by every enrichment client."""

import pytest
from sqlmodel import Session, select

from crate.model.orm import ApiResponseCache
from crate.services.enrichment.cache import ResponseCache

pytestmark = pytest.mark.unit


def test_miss_returns_none(session: Session) -> None:
    cache = ResponseCache(session, source="reccobeats")
    assert cache.get("audio-features:abc") is None


def test_put_then_get_round_trips_payload(session: Session) -> None:
    cache = ResponseCache(session, source="reccobeats")
    payload = {"content": [{"id": "x", "energy": 0.5}]}
    cache.put("audio-features:abc", payload)
    assert cache.get("audio-features:abc") == payload


def test_sources_are_isolated(session: Session) -> None:
    ResponseCache(session, source="reccobeats").put("k", {"from": "reccobeats"})
    ResponseCache(session, source="lastfm").put("k", {"from": "lastfm"})
    assert ResponseCache(session, source="reccobeats").get("k") == {"from": "reccobeats"}
    assert ResponseCache(session, source="lastfm").get("k") == {"from": "lastfm"}


def test_put_same_key_overwrites_instead_of_duplicating(session: Session) -> None:
    cache = ResponseCache(session, source="musicbrainz")
    cache.put("isrc:USX", {"v": 1})
    cache.put("isrc:USX", {"v": 2})
    assert cache.get("isrc:USX") == {"v": 2}
    rows = session.exec(select(ApiResponseCache)).all()
    assert len(rows) == 1


def test_long_keys_are_stored_safely(session: Session) -> None:
    """Keys beyond the column width must not error or collide."""
    cache = ResponseCache(session, source="lastfm")
    long_a = "similar:" + "a" * 400
    long_b = "similar:" + "a" * 399 + "b"
    cache.put(long_a, {"v": "a"})
    cache.put(long_b, {"v": "b"})
    assert cache.get(long_a) == {"v": "a"}
    assert cache.get(long_b) == {"v": "b"}
