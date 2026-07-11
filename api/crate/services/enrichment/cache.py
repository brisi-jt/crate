"""Database-backed cache for third-party API responses.

Every enrichment source is rate-limited, so responses are kept in MySQL and
re-runs read from here instead of re-fetching.
"""

import hashlib
from typing import Any

from sqlmodel import Session, select

from crate.model.orm import ApiResponseCache
from crate.model.orm.base import utcnow

# Width of api_response_cache.cache_key; longer keys are hashed to fit.
MAX_KEY_LENGTH = 255


def _storage_key(key: str) -> str:
    if len(key) <= MAX_KEY_LENGTH:
        return key
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()


class ResponseCache:
    """Get/put JSON payloads for one source (reccobeats, lastfm, ...)."""

    def __init__(self, session: Session, *, source: str) -> None:
        self._session = session
        self._source = source

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._find(_storage_key(key))
        return row.payload if row else None

    def put(self, key: str, payload: dict[str, Any]) -> None:
        storage_key = _storage_key(key)
        row = self._find(storage_key)
        if row is None:
            row = ApiResponseCache(source=self._source, cache_key=storage_key, payload=payload)
        else:
            row.payload = payload
            row.fetched_at = utcnow()
        self._session.add(row)
        self._session.commit()

    def _find(self, storage_key: str) -> ApiResponseCache | None:
        return self._session.exec(
            select(ApiResponseCache)
            .where(ApiResponseCache.source == self._source)
            .where(ApiResponseCache.cache_key == storage_key)
        ).first()
