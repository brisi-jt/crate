"""Preview refresh service + endpoint — fully offline (fake Deezer source)."""

import pytest
from sqlmodel import Session, select

from crate.model.enums import (
    CandidateSource,
    FeatureStatus,
    RadioItemKind,
    RadioSeedKind,
)
from crate.model.orm import (
    DiscoveryCandidate,
    Playlist,
    RadioItem,
    RadioSession,
    Track,
    TrackFeatures,
    User,
)
from crate.services.enrichment.models import DeezerTrack
from crate.services.previews.refresh import (
    PREVIEW_EXPIRES_HINT_SECONDS,
    PreviewTargetNotFound,
    PreviewUnresolvable,
    refresh_preview,
)

pytestmark = pytest.mark.unit


class FakeDeezer:
    """Records calls and returns a canned result (or None for no preview)."""

    def __init__(self, result: DeezerTrack | None) -> None:
        self._result = result
        self.calls: list[tuple[str, str, bool]] = []

    async def search_preview(
        self, title: str, artist: str, *, force: bool = False
    ) -> DeezerTrack | None:
        self.calls.append((title, artist, force))
        return self._result


def hit(url: str = "https://cdnt-preview.dzcdn.net/api/1/fresh.mp3") -> DeezerTrack:
    return DeezerTrack(id=1, title="t", preview=url, artist_name="A")


def add_track(session: Session, name: str, artist: str) -> Track:
    track = Track(spotify_id=f"sp-{name}", name=name, artists=[{"name": artist}])
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def add_candidate(session: Session, user: User) -> DiscoveryCandidate:
    playlist = Playlist(user_id=user.id, spotify_id="pl", name="PL", snapshot_id="s")
    session.add(playlist)
    session.commit()
    session.refresh(playlist)
    candidate = DiscoveryCandidate(
        user_id=user.id,
        playlist_id=playlist.id,
        source=CandidateSource.lastfm,
        title="Cand Title",
        artist="Cand Artist",
        dedup_key="cand artist|cand title",
        preview_url="https://old/expired.mp3",
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def add_radio_item(session: Session, user: User) -> RadioItem:
    rs = RadioSession(user_id=user.id, seed_kind=RadioSeedKind.playlist, label="X")
    session.add(rs)
    session.commit()
    session.refresh(rs)
    item = RadioItem(
        session_id=rs.id,
        position=0,
        kind=RadioItemKind.library,
        title="Radio Title",
        artist="Radio Artist",
        preview_url="https://old/expired.mp3",
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


# -- track -----------------------------------------------------------------


async def test_track_refresh_returns_fresh_url_and_forces_bypass(
    session: Session, user: User
) -> None:
    track = add_track(session, "Song", "Band")
    session.add(TrackFeatures(track_id=track.id, status=FeatureStatus.present))
    session.commit()
    deezer = FakeDeezer(hit("https://fresh/1.mp3"))

    result = await refresh_preview(session, deezer, user_id=user.id, track_id=track.id)

    assert result.preview_url == "https://fresh/1.mp3"
    assert result.expires_hint_seconds == PREVIEW_EXPIRES_HINT_SECONDS
    # The Deezer lookup must bypass the (expired) cache.
    assert deezer.calls == [("Song", "Band", True)]
    features = session.exec(select(TrackFeatures).where(TrackFeatures.track_id == track.id)).one()
    assert features.preview_resolved is True


async def test_track_refresh_404_marks_preview_unresolved(session: Session, user: User) -> None:
    track = add_track(session, "Ghost", "Nobody")
    session.add(TrackFeatures(track_id=track.id, status=FeatureStatus.missing))
    session.commit()
    deezer = FakeDeezer(None)

    with pytest.raises(PreviewUnresolvable):
        await refresh_preview(session, deezer, user_id=user.id, track_id=track.id)

    features = session.exec(select(TrackFeatures).where(TrackFeatures.track_id == track.id)).one()
    assert features.preview_resolved is False


async def test_track_refresh_missing_track_is_not_found(session: Session, user: User) -> None:
    with pytest.raises(PreviewTargetNotFound):
        await refresh_preview(session, FakeDeezer(hit()), user_id=user.id, track_id=999)


# -- candidate -------------------------------------------------------------


async def test_candidate_refresh_persists_fresh_url(session: Session, user: User) -> None:
    candidate = add_candidate(session, user)
    deezer = FakeDeezer(hit("https://fresh/cand.mp3"))

    result = await refresh_preview(session, deezer, user_id=user.id, candidate_id=candidate.id)

    assert result.preview_url == "https://fresh/cand.mp3"
    session.refresh(candidate)
    assert candidate.preview_url == "https://fresh/cand.mp3"
    assert deezer.calls == [("Cand Title", "Cand Artist", True)]


async def test_candidate_refresh_404_clears_stale_url(session: Session, user: User) -> None:
    candidate = add_candidate(session, user)
    with pytest.raises(PreviewUnresolvable):
        await refresh_preview(session, FakeDeezer(None), user_id=user.id, candidate_id=candidate.id)
    session.refresh(candidate)
    assert candidate.preview_url is None


async def test_candidate_of_other_user_is_not_found(session: Session, user: User) -> None:
    candidate = add_candidate(session, user)
    other = User(clerk_user_id="other")
    session.add(other)
    session.commit()
    session.refresh(other)
    with pytest.raises(PreviewTargetNotFound):
        await refresh_preview(
            session, FakeDeezer(hit()), user_id=other.id, candidate_id=candidate.id
        )


# -- radio item ------------------------------------------------------------


async def test_radio_item_refresh_persists_fresh_url(session: Session, user: User) -> None:
    item = add_radio_item(session, user)
    deezer = FakeDeezer(hit("https://fresh/radio.mp3"))

    result = await refresh_preview(session, deezer, user_id=user.id, radio_item_id=item.id)

    assert result.preview_url == "https://fresh/radio.mp3"
    session.refresh(item)
    assert item.preview_url == "https://fresh/radio.mp3"


async def test_radio_item_of_other_user_is_not_found(session: Session, user: User) -> None:
    item = add_radio_item(session, user)
    other = User(clerk_user_id="other2")
    session.add(other)
    session.commit()
    session.refresh(other)
    with pytest.raises(PreviewTargetNotFound):
        await refresh_preview(session, FakeDeezer(hit()), user_id=other.id, radio_item_id=item.id)


# -- dispatch guard --------------------------------------------------------


async def test_requires_exactly_one_target(session: Session, user: User) -> None:
    with pytest.raises(ValueError):
        await refresh_preview(session, FakeDeezer(hit()), user_id=user.id)
    with pytest.raises(ValueError):
        await refresh_preview(
            session, FakeDeezer(hit()), user_id=user.id, track_id=1, candidate_id=2
        )
