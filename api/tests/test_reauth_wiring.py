"""Re-auth classification through the credential wiring.

Spotify's 6-month refresh-token lifetime surfaces as `400 invalid_grant` on
refresh. These tests pin the mapping from that signal (vs a generic refresh
rejection) to credential state and problem+json codes.
"""

import pytest
from sqlmodel import Session

from crate.errors import AppError
from crate.model.enums import CredentialStatus, ReauthReason
from crate.model.orm import SpotifyCredential, User
from crate.services.crypto import get_cipher
from crate.services.mutations.wiring import spotify_client_for_user
from crate.services.spotify.client import SpotifyReauthRequired
from crate.services.sync import SyncService, run_sync_for_user

pytestmark = pytest.mark.unit


@pytest.fixture
def credential(session: Session, user: User) -> SpotifyCredential:
    row = SpotifyCredential(
        user_id=user.id,
        refresh_token_encrypted=get_cipher().encrypt("stored-refresh-token"),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _raise_reauth(reason: ReauthReason):
    async def run(self) -> None:
        raise SpotifyReauthRequired("refresh rejected", reason=reason)

    return run


async def test_sync_expired_reason_flips_status_and_surfaces_expired_code(
    session: Session, user: User, credential: SpotifyCredential, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SyncService, "run", _raise_reauth(ReauthReason.token_expired))

    with pytest.raises(AppError) as exc_info:
        await run_sync_for_user(session, user)

    assert exc_info.value.status == 409
    assert exc_info.value.error_code == "SPOTIFY_SESSION_EXPIRED"
    session.refresh(credential)
    assert credential.status == CredentialStatus.needs_reauth_expired


async def test_sync_generic_rejection_keeps_generic_code(
    session: Session, user: User, credential: SpotifyCredential, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SyncService, "run", _raise_reauth(ReauthReason.refresh_rejected))

    with pytest.raises(AppError) as exc_info:
        await run_sync_for_user(session, user)

    assert exc_info.value.error_code == "SPOTIFY_REAUTH_REQUIRED"
    session.refresh(credential)
    assert credential.status == CredentialStatus.needs_reauth


async def test_sync_precheck_surfaces_expired_code_for_stored_expired_status(
    session: Session, user: User, credential: SpotifyCredential
) -> None:
    credential.status = CredentialStatus.needs_reauth_expired
    session.add(credential)
    session.commit()

    with pytest.raises(AppError) as exc_info:
        await run_sync_for_user(session, user)

    assert exc_info.value.error_code == "SPOTIFY_SESSION_EXPIRED"


async def test_wiring_expired_reason_flips_status_and_surfaces_expired_code(
    session: Session, user: User, credential: SpotifyCredential
) -> None:
    with pytest.raises(AppError) as exc_info:
        async with spotify_client_for_user(session, user):
            raise SpotifyReauthRequired("refresh rejected", reason=ReauthReason.token_expired)

    assert exc_info.value.error_code == "SPOTIFY_SESSION_EXPIRED"
    session.refresh(credential)
    assert credential.status == CredentialStatus.needs_reauth_expired


async def test_wiring_precheck_surfaces_expired_code_for_stored_expired_status(
    session: Session, user: User, credential: SpotifyCredential
) -> None:
    credential.status = CredentialStatus.needs_reauth_expired
    session.add(credential)
    session.commit()

    with pytest.raises(AppError) as exc_info:
        async with spotify_client_for_user(session, user):
            raise AssertionError("client must not be handed out")

    assert exc_info.value.error_code == "SPOTIFY_SESSION_EXPIRED"
