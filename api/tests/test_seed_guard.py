"""seed_demo refuses to wipe rows for a user with an active Spotify credential."""

import importlib.util
from pathlib import Path

import pytest
from sqlmodel import Session, select

from crate.model.enums import CredentialStatus, PlaylistSyncStatus
from crate.model.orm import Playlist, SpotifyCredential, User, utcnow

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"


@pytest.fixture(scope="module")
def seed_demo():
    spec = importlib.util.spec_from_file_location("seed_demo_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_playlist(session: Session, user: User) -> None:
    session.add(
        Playlist(
            user_id=user.id,
            spotify_id="sp-live",
            name="Live library playlist",
            snapshot_id="snap",
            status=PlaylistSyncStatus.synced,
            last_synced_at=utcnow(),
        )
    )
    session.commit()


def playlist_count(session: Session, user: User) -> int:
    return len(session.exec(select(Playlist).where(Playlist.user_id == user.id)).all())


def test_wipe_refuses_user_with_active_credential(seed_demo, session: Session, user: User) -> None:
    session.add(SpotifyCredential(user_id=user.id, refresh_token_encrypted="ct"))
    add_playlist(session, user)

    with pytest.raises(RuntimeError, match="active Spotify credential"):
        seed_demo.wipe_user_rows(session, user)

    assert playlist_count(session, user) == 1  # nothing was deleted


def test_wipe_allows_active_credential_when_forced(seed_demo, session: Session, user: User) -> None:
    session.add(SpotifyCredential(user_id=user.id, refresh_token_encrypted="ct"))
    add_playlist(session, user)

    seed_demo.wipe_user_rows(session, user, force_real_account=True)

    assert playlist_count(session, user) == 0


def test_wipe_allows_user_without_credential(seed_demo, session: Session, user: User) -> None:
    add_playlist(session, user)
    seed_demo.wipe_user_rows(session, user)
    assert playlist_count(session, user) == 0


def test_wipe_allows_credential_needing_reauth(seed_demo, session: Session, user: User) -> None:
    session.add(
        SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted="ct",
            status=CredentialStatus.needs_reauth,
        )
    )
    add_playlist(session, user)

    seed_demo.wipe_user_rows(session, user)

    assert playlist_count(session, user) == 0
