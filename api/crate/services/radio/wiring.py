"""Production wiring for radio session builds.

Library tracks need preview audio resolved at build time (candidates already
carry theirs); the Deezer client supplies it, reading through the shared
response cache so repeat sessions over the same material cost nothing.
"""

from sqlmodel import Session

from crate.model.orm import RadioSession, User
from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.deezer import DeezerClient
from crate.services.radio.service import create_radio_session


async def build_radio_for_user(
    session: Session,
    user: User,
    playlist_id: int | None,
    track_ids: list[int] | None,
    genre_name: str | None,
    length: int,
    discovery_ratio: float,
) -> RadioSession:
    deezer = DeezerClient(cache=ResponseCache(session, source="deezer"))
    try:
        return await create_radio_session(
            session,
            user,
            playlist_id=playlist_id,
            track_ids=track_ids,
            genre_name=genre_name,
            length=length,
            discovery_ratio=discovery_ratio,
            previews=deezer,
        )
    finally:
        await deezer.aclose()
