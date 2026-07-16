"""Production wiring for preview refresh.

Builds a Deezer client (interactive 4 req/s cadence, reading through the shared
response cache) for one refresh, forces a fresh lookup past the ~20-minute
cache, persists the result, and closes the client.
"""

from sqlmodel import Session

from crate.model.orm import User
from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.deezer import DeezerClient
from crate.services.previews.refresh import RefreshedPreview, refresh_preview


async def refresh_preview_for_user(
    session: Session,
    user: User,
    *,
    track_id: int | None = None,
    candidate_id: int | None = None,
    radio_item_id: int | None = None,
) -> RefreshedPreview:
    assert user.id is not None
    deezer = DeezerClient(cache=ResponseCache(session, source="deezer"))
    try:
        return await refresh_preview(
            session,
            deezer,
            user_id=user.id,
            track_id=track_id,
            candidate_id=candidate_id,
            radio_item_id=radio_item_id,
        )
    finally:
        await deezer.aclose()
