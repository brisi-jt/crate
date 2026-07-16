"""End-to-end rotation guard through the credential funnels + scheduler.

Ties the two layers together: (1) an unreachable engine gates the refresh so
Spotify's token endpoint is never contacted and the credential row is left
intact; (2) a persist failure on a just-rotated token spills to disk and the
next healthy reconcile restores it; (3) the scheduler treats StorageUnavailable
like the existing skip — log-once, re-arm, no crash, no reauth flip.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from crate.model.enums import CredentialStatus
from crate.model.orm import SpotifyCredential, User
from crate.services.crypto import get_cipher
from crate.services.spill import reconcile_spill, spill_path_for_user
from crate.services.storage import StorageUnavailable

pytestmark = pytest.mark.unit


@pytest.fixture
def spill_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    import crate.settings

    crate.settings.get_settings.cache_clear()
    monkeypatch.setenv("CRATE_TOKEN_SPILL_PATH", str(tmp_path / "spill"))
    crate.settings.get_settings.cache_clear()
    yield tmp_path / "spill"
    crate.settings.get_settings.cache_clear()


@pytest.fixture
def credential(session: Session, user: User) -> SpotifyCredential:
    row = SpotifyCredential(
        user_id=user.id,
        refresh_token_encrypted=get_cipher().encrypt("stored-refresh-token"),
        status=CredentialStatus.active,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def test_unreachable_storage_never_calls_token_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    user: User,
    credential: SpotifyCredential,
) -> None:
    from crate.services.mutations import wiring

    # Force the preflight to report the DB is down.
    monkeypatch.setattr(
        wiring, "ping_engine", lambda _engine: (_ for _ in ()).throw(StorageUnavailable("down"))
    )

    with pytest.raises(StorageUnavailable):
        async with wiring.spotify_client_for_user(session, user) as client:
            await client.ensure_access_token(force_refresh=True)

    # Credential row is untouched and never flipped to needs_reauth.
    session.refresh(credential)
    assert credential.status == CredentialStatus.active
    assert get_cipher().decrypt(credential.refresh_token_encrypted) == "stored-refresh-token"


async def test_rotated_token_persist_failure_spills_then_reconciles(
    spill_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    user: User,
    credential: SpotifyCredential,
) -> None:
    from crate.services.mutations import wiring
    from crate.services.spotify.client import SpotifyClient

    monkeypatch.setattr(wiring, "ping_engine", lambda _engine: None)

    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rotated-refresh",
            },
        )

    # Force the funnel-built client onto a MockTransport so the refresh never
    # touches the network but still rotates the token.
    real_client_init = SpotifyClient.__init__

    def mock_transport_init(self: SpotifyClient, **kwargs: object) -> None:
        kwargs["transport"] = httpx.MockTransport(token_handler)
        real_client_init(self, **kwargs)

    monkeypatch.setattr(SpotifyClient, "__init__", mock_transport_init)

    # Refresh succeeds and rotates; the commit then fails (DB died in the race).
    real_commit = Session.commit
    boom = {"armed": True}

    def flaky_commit(self: Session) -> None:
        if boom["armed"]:
            boom["armed"] = False
            raise StorageUnavailable("db died mid-write")
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", flaky_commit)

    with pytest.raises(StorageUnavailable):
        async with wiring.spotify_client_for_user(session, user) as client:
            await client.ensure_access_token(force_refresh=True)

    monkeypatch.setattr(Session, "commit", real_commit)
    monkeypatch.setattr(SpotifyClient, "__init__", real_client_init)

    # The rotated token was spilled (not lost).
    assert spill_path_for_user(user.id).exists()

    # A later healthy reconcile brings it back into the DB.
    restored = reconcile_spill(session, user.id)
    assert restored is True
    session.refresh(credential)
    assert get_cipher().decrypt(credential.refresh_token_encrypted) == "rotated-refresh"
    assert not spill_path_for_user(user.id).exists()


async def test_scheduler_skips_on_storage_unavailable_log_once(
    session: Session,
    user: User,
    credential: SpotifyCredential,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from crate.scheduler import AccountScheduler

    async def down_job(_session: Session, _user: User) -> None:
        raise StorageUnavailable("db down")

    engine = session.get_bind()
    # The scheduler closes the session it opens; give each pass its own so the
    # shared fixture session is not expunged mid-test.
    scheduler = AccountScheduler(
        session_factory=lambda: Session(engine),
        recent_job=down_job,
        nightly_job=down_job,
        top_job=down_job,
    )

    with caplog.at_level(logging.INFO, logger="crate.scheduler"):
        await scheduler.run_recent_pass()
        await scheduler.run_recent_pass()

    records = [r for r in caplog.records if r.name == "crate.scheduler"]
    assert len(records) == 1  # skip logged once, not per tick
    fresh = Session(engine).get(SpotifyCredential, credential.id)
    assert fresh is not None
    assert fresh.status == CredentialStatus.active  # never flipped to reauth
