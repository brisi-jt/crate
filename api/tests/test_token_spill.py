"""Disk-spill fallback for a rotated refresh token the DB could not store.

Between a passing reachability preflight and the commit the DB can still die.
A just-rotated token is unrecoverable if lost, so it spills to an encrypted
0600 file and reconciles back into the DB on the next healthy tick. Reconcile
never clobbers a newer stored credential and is idempotent.
"""

import json
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from crate.model.enums import CredentialStatus
from crate.model.orm import SpotifyCredential, User, utcnow
from crate.services.crypto import get_cipher
from crate.services.spill import (
    read_spill,
    reconcile_all_spills,
    reconcile_spill,
    spill_path_for_user,
    write_spill,
)

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
        refresh_token_encrypted=get_cipher().encrypt("db-refresh-token"),
        status=CredentialStatus.active,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_write_spill_is_encrypted_and_0600(spill_dir: Path, user: User) -> None:
    cipher = get_cipher()
    write_spill(user.id, cipher.encrypt("rotated-secret"), rotated_at=utcnow())

    path = spill_path_for_user(user.id)
    assert path.exists()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    raw = path.read_text()
    assert "rotated-secret" not in raw  # ciphertext only, never plaintext
    payload = json.loads(raw)
    assert payload["user_id"] == user.id
    assert cipher.decrypt(payload["refresh_token_encrypted"]) == "rotated-secret"


def test_reconcile_restores_newer_spill_into_db_and_deletes_it(
    spill_dir: Path, session: Session, credential: SpotifyCredential
) -> None:
    cipher = get_cipher()
    newer = utcnow()
    # Make the DB row look older than the spill.
    credential.updated_at = newer.replace(year=newer.year - 1)
    session.add(credential)
    session.commit()

    write_spill(credential.user_id, cipher.encrypt("spilled-refresh"), rotated_at=newer)
    restored = reconcile_spill(session, credential.user_id)

    assert restored is True
    session.refresh(credential)
    assert cipher.decrypt(credential.refresh_token_encrypted) == "spilled-refresh"
    assert not spill_path_for_user(credential.user_id).exists()


def test_reconcile_is_idempotent(
    spill_dir: Path, session: Session, credential: SpotifyCredential
) -> None:
    cipher = get_cipher()
    newer = utcnow()
    credential.updated_at = newer.replace(year=newer.year - 1)
    session.add(credential)
    session.commit()
    write_spill(credential.user_id, cipher.encrypt("spilled-refresh"), rotated_at=newer)

    assert reconcile_spill(session, credential.user_id) is True
    # Second run: spill already consumed → no-op, no error, no clobber.
    assert reconcile_spill(session, credential.user_id) is False
    session.refresh(credential)
    assert cipher.decrypt(credential.refresh_token_encrypted) == "spilled-refresh"


def test_reconcile_ignores_and_cleans_older_spill(
    spill_dir: Path, session: Session, credential: SpotifyCredential
) -> None:
    cipher = get_cipher()
    now = utcnow()
    # DB credential is NEWER than the spill (e.g. a fresh re-auth landed).
    credential.refresh_token_encrypted = cipher.encrypt("db-newer-refresh")
    credential.updated_at = now
    session.add(credential)
    session.commit()

    stale = now.replace(year=now.year - 1)
    write_spill(credential.user_id, cipher.encrypt("stale-spill"), rotated_at=stale)

    restored = reconcile_spill(session, credential.user_id)

    assert restored is False
    session.refresh(credential)
    # DB value untouched; stale spill removed.
    assert cipher.decrypt(credential.refresh_token_encrypted) == "db-newer-refresh"
    assert not spill_path_for_user(credential.user_id).exists()


def test_reconcile_all_spills_scans_every_user(
    spill_dir: Path, session: Session, credential: SpotifyCredential
) -> None:
    cipher = get_cipher()
    newer = utcnow()
    credential.updated_at = newer.replace(year=newer.year - 1)
    session.add(credential)
    session.commit()
    write_spill(credential.user_id, cipher.encrypt("spilled-refresh"), rotated_at=newer)

    count = reconcile_all_spills(session)

    assert count == 1
    session.refresh(credential)
    assert cipher.decrypt(credential.refresh_token_encrypted) == "spilled-refresh"


def test_read_spill_absent_is_none(spill_dir: Path, user: User) -> None:
    assert read_spill(user.id) is None
