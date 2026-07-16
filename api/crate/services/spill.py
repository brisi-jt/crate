"""Disk-spill fallback for a rotated refresh token the DB could not store.

The reachability preflight (``storage.ping_engine``) closes the common case,
but the database can still die in the window between a passing check and the
commit. A just-rotated refresh token is unrecoverable if lost, so on a persist
failure the encrypted token is written to a small per-user file (0600, cipher
text only — never plaintext). On startup and on every healthy scheduler tick we
reconcile: a spill newer than the stored credential is restored into the DB and
removed; an older or equal spill is discarded (a fresh re-auth must win).
Reconcile is idempotent — once the spill is consumed the next run is a no-op.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from crate.model.orm import SpotifyCredential, utcnow
from crate.settings import get_settings

_SPILL_MODE = 0o600


def spill_dir() -> Path:
    """Directory holding per-user spill files (created on demand)."""
    configured = get_settings().token_spill_path
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "token_spill"


def spill_path_for_user(user_id: int) -> Path:
    return spill_dir() / f"{user_id}.json"


def write_spill(user_id: int, refresh_token_encrypted: str, *, rotated_at: datetime) -> Path:
    """Persist a rotated (encrypted) refresh token to a 0600 file, atomically."""
    path = spill_path_for_user(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_id": user_id,
        "refresh_token_encrypted": refresh_token_encrypted,
        "rotated_at": rotated_at.isoformat(),
    }
    tmp = path.with_suffix(".json.tmp")
    # Create with 0600 from the start so the secret is never briefly world-readable.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _SPILL_MODE)
    with os.fdopen(fd, "w") as handle:
        json.dump(payload, handle)
    tmp.replace(path)
    path.chmod(_SPILL_MODE)
    return path


def read_spill(user_id: int) -> dict | None:
    path = spill_path_for_user(user_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _delete_spill(user_id: int) -> None:
    spill_path_for_user(user_id).unlink(missing_ok=True)


def reconcile_spill(session: Session, user_id: int) -> bool:
    """Restore a newer spilled token into the DB; discard an older one.

    Returns True iff a spill was restored into the credential. Safe to run
    repeatedly — a consumed spill is gone, so re-runs return False.
    """
    payload = read_spill(user_id)
    if payload is None:
        return False

    credential = session.exec(
        select(SpotifyCredential).where(SpotifyCredential.user_id == user_id)
    ).first()
    if credential is None:
        # No credential to restore into (disconnected/deleted) — drop the spill.
        _delete_spill(user_id)
        return False

    rotated_at = datetime.fromisoformat(payload["rotated_at"])
    if rotated_at <= credential.updated_at:
        # The stored credential is at least as new (e.g. a re-auth landed) —
        # never clobber it with a stale spill.
        _delete_spill(user_id)
        return False

    credential.refresh_token_encrypted = payload["refresh_token_encrypted"]
    credential.updated_at = utcnow()
    session.add(credential)
    session.commit()
    _delete_spill(user_id)
    return True


def reconcile_all_spills(session: Session) -> int:
    """Reconcile every user with a spill file. Returns the count restored."""
    directory = spill_dir()
    if not directory.exists():
        return 0
    restored = 0
    for path in directory.glob("*.json"):
        try:
            user_id = int(path.stem)
        except ValueError:
            continue
        if reconcile_spill(session, user_id):
            restored += 1
    return restored
