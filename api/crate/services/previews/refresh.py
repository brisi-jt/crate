"""Re-resolve a fresh Deezer preview URL for one playable entity.

Deezer preview URLs expire ~20 minutes after issue, so the deck and radio get
403s at play time on a URL that was fine when the queue was built. This service
re-searches Deezer (bypassing the stale cache) and persists the fresh URL to the
entity's row, so the client can retry-then-play.

The three playable entities differ in where a preview lives:

- radio_item / candidate: carry a ``preview_url`` string column — updated in place.
- track: the catalog row has no preview_url column (a track is never played by a
  raw preview URL — only candidates and radio items are). We still resolve and
  return a fresh URL for immediate play and record the outcome on
  ``TrackFeatures.preview_resolved`` (True on hit, False on miss), matching the
  enrichment ladder's tri-state marker.

"no resolvable preview" is a domain 404 (``PreviewUnresolvable``): the entity is
marked so callers stop retrying (track → preview_resolved=False; candidate /
radio_item → preview_url stays null, its existing "no preview" signal).
"""

from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session, select

from crate.model.enums import FeatureStatus
from crate.model.orm import DiscoveryCandidate, RadioItem, RadioSession, Track, TrackFeatures
from crate.services.enrichment.models import DeezerTrack

# How long a freshly-issued Deezer preview URL stays valid, in seconds. The
# client uses this to schedule a proactive refresh before the URL dies.
PREVIEW_EXPIRES_HINT_SECONDS = 1200


class PreviewSource(Protocol):
    async def search_preview(
        self, title: str, artist: str, *, force: bool = False
    ) -> DeezerTrack | None: ...


class PreviewUnresolvable(Exception):
    """No fresh preview could be found for the entity (rendered as a 404)."""

    def __init__(self, kind: str, entity_id: int) -> None:
        super().__init__(f"no resolvable preview for {kind} {entity_id}")
        self.kind = kind
        self.entity_id = entity_id


class PreviewTargetNotFound(Exception):
    """The named entity does not exist for this user (rendered as a 404)."""

    def __init__(self, kind: str, entity_id: int) -> None:
        super().__init__(f"no {kind} with id {entity_id}")
        self.kind = kind
        self.entity_id = entity_id


@dataclass(frozen=True)
class RefreshedPreview:
    kind: str
    entity_id: int
    preview_url: str
    expires_hint_seconds: int = PREVIEW_EXPIRES_HINT_SECONDS


def _primary_artist(track: Track) -> str:
    for credited in track.artists:
        name = credited.get("name")
        if name:
            return str(name)
    return ""


async def refresh_track_preview(
    session: Session, previews: PreviewSource, track_id: int
) -> RefreshedPreview:
    track = session.get(Track, track_id)
    if track is None:
        raise PreviewTargetNotFound("track", track_id)
    result = await previews.search_preview(track.name, _primary_artist(track), force=True)
    features = session.exec(select(TrackFeatures).where(TrackFeatures.track_id == track_id)).first()
    if result is None or not result.preview:
        if features is not None:
            features.preview_resolved = False
            session.add(features)
            session.commit()
        raise PreviewUnresolvable("track", track_id)
    # The catalog track has no preview_url column; record that a preview exists
    # (the URL itself is transient and returned for immediate play).
    if features is not None and features.status != FeatureStatus.missing:
        features.preview_resolved = True
        session.add(features)
        session.commit()
    return RefreshedPreview("track", track_id, result.preview)


async def refresh_candidate_preview(
    session: Session, previews: PreviewSource, user_id: int, candidate_id: int
) -> RefreshedPreview:
    candidate = session.exec(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.id == candidate_id)
        .where(DiscoveryCandidate.user_id == user_id)
    ).first()
    if candidate is None:
        raise PreviewTargetNotFound("candidate", candidate_id)
    result = await previews.search_preview(candidate.title, candidate.artist, force=True)
    if result is None or not result.preview:
        # Null preview_url is the candidate's standing "no preview" signal.
        candidate.preview_url = None
        session.add(candidate)
        session.commit()
        raise PreviewUnresolvable("candidate", candidate_id)
    candidate.preview_url = result.preview
    session.add(candidate)
    session.commit()
    return RefreshedPreview("candidate", candidate_id, result.preview)


async def refresh_radio_item_preview(
    session: Session, previews: PreviewSource, user_id: int, radio_item_id: int
) -> RefreshedPreview:
    item = session.exec(
        select(RadioItem)
        .join(RadioSession, RadioSession.id == RadioItem.session_id)
        .where(RadioItem.id == radio_item_id)
        .where(RadioSession.user_id == user_id)
    ).first()
    if item is None:
        raise PreviewTargetNotFound("radio_item", radio_item_id)
    result = await previews.search_preview(item.title, item.artist, force=True)
    if result is None or not result.preview:
        item.preview_url = None
        session.add(item)
        session.commit()
        raise PreviewUnresolvable("radio_item", radio_item_id)
    item.preview_url = result.preview
    session.add(item)
    session.commit()
    return RefreshedPreview("radio_item", radio_item_id, result.preview)


async def refresh_preview(
    session: Session,
    previews: PreviewSource,
    *,
    user_id: int,
    track_id: int | None = None,
    candidate_id: int | None = None,
    radio_item_id: int | None = None,
) -> RefreshedPreview:
    """Dispatch to the right entity. Exactly one id must be given."""
    given = [i for i in (track_id, candidate_id, radio_item_id) if i is not None]
    if len(given) != 1:
        raise ValueError("exactly one of track_id, candidate_id, radio_item_id is required")
    if track_id is not None:
        return await refresh_track_preview(session, previews, track_id)
    if candidate_id is not None:
        return await refresh_candidate_preview(session, previews, user_id, candidate_id)
    assert radio_item_id is not None
    return await refresh_radio_item_preview(session, previews, user_id, radio_item_id)
