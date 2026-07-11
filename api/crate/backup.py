"""Backup bookkeeping shared by the backup script, scheduler, and sync status.

The dump/restore orchestration lives in ``scripts/backup_db.py``; this module
holds the pieces worth unit-testing and importing from the API — retention
selection, the manifest shape, per-table row counts, and the status sidecar
that ``GET /v1/sync/status`` reads.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine

from crate.model.orm import utcnow
from crate.settings import Settings

TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
STATUS_FILENAME = "backup_status.json"

_REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_backup_dir(settings: Settings) -> Path:
    """Where dumps, manifests, and the status sidecar live."""
    if settings.backup_dir:
        return Path(settings.backup_dir)
    return _REPO_ROOT / "backups" / "crate"


# --- json helpers ------------------------------------------------------------


def write_json_atomic(path: Path, data: dict) -> None:
    """Write ``data`` as JSON via a temp file + rename so readers never see a partial file."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict | None:
    """Read a JSON file, or ``None`` when it does not exist."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# --- manifest ----------------------------------------------------------------


def build_manifest(
    *, database: str, dump: str, created_at: datetime, tables: dict[str, int]
) -> dict:
    """Sidecar written next to each dump: per-table row counts at dump time."""
    return {
        "database": database,
        "dump": dump,
        "created_at": created_at.isoformat(),
        "tables": dict(sorted(tables.items())),
    }


def manifest_table_mismatches(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    """Human-readable differences between manifest counts and restored counts."""
    messages: list[str] = []
    for name in sorted(expected.keys() - actual.keys()):
        messages.append(f"table {name!r} is in the manifest but missing from the restore")
    for name in sorted(actual.keys() - expected.keys()):
        messages.append(f"table {name!r} appeared in the restore but is not in the manifest")
    for name in sorted(expected.keys() & actual.keys()):
        if expected[name] != actual[name]:
            messages.append(
                f"table {name!r} row count drifted: manifest {expected[name]}, "
                f"restored {actual[name]}"
            )
    return messages


def table_row_counts(engine: Engine) -> dict[str, int]:
    """Exact ``COUNT(*)`` per base table (MySQL only)."""
    with engine.connect() as conn:
        tables = [
            row[0]
            for row in conn.exec_driver_sql("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
        ]
        return {
            name: int(conn.exec_driver_sql(f"SELECT COUNT(*) FROM `{name}`").scalar_one())
            for name in tables
        }


# --- retention ----------------------------------------------------------------


def select_prunable(
    entries: list[tuple[str, datetime]],
    *,
    now: datetime,
    keep_last: int = 30,
    daily_days: int = 14,
) -> list[str]:
    """Dump names safe to delete under the retention policy.

    Retained: the newest ``keep_last`` dumps, plus the newest dump of each UTC
    day within the trailing ``daily_days`` window. Everything else is prunable.
    Pure function — callers do the actual deletion.
    """
    ordered = sorted(entries, key=lambda entry: entry[1], reverse=True)
    keep = {name for name, _at in ordered[:keep_last]}

    cutoff = (now - timedelta(days=daily_days)).date()
    newest_per_day: dict[date, tuple[str, datetime]] = {}
    for name, at in entries:
        if at.date() < cutoff:
            continue
        current = newest_per_day.get(at.date())
        if current is None or at > current[1]:
            newest_per_day[at.date()] = (name, at)
    keep |= {name for name, _at in newest_per_day.values()}

    return sorted(name for name, _at in entries if name not in keep)


# --- status sidecar -------------------------------------------------------------


@dataclass(frozen=True)
class BackupStatus:
    """What the API surfaces about backup health; ``None`` = never attempted."""

    last_backup_at: datetime | None
    backup_ok: bool | None


def read_backup_status(backup_dir: Path) -> BackupStatus:
    data = read_json(backup_dir / STATUS_FILENAME)
    if not data:
        return BackupStatus(last_backup_at=None, backup_ok=None)
    last_success = data.get("last_success_at")
    return BackupStatus(
        last_backup_at=datetime.fromisoformat(last_success) if last_success else None,
        backup_ok=data.get("last_attempt_ok"),
    )


def write_backup_status(
    backup_dir: Path,
    *,
    ok: bool,
    dump: str | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    """Record a backup attempt, preserving the last-success fields across failures."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    at = now or utcnow()
    path = backup_dir / STATUS_FILENAME
    data = read_json(path) or {}
    data.update({"last_attempt_at": at.isoformat(), "last_attempt_ok": ok, "error": error})
    if ok:
        data["last_success_at"] = at.isoformat()
        if dump is not None:
            data["last_dump"] = dump
    write_json_atomic(path, data)


def record_verify(backup_dir: Path, *, ok: bool, dump: str, now: datetime | None = None) -> None:
    """Record the outcome of a restore-verify pass in the status sidecar."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    at = now or utcnow()
    path = backup_dir / STATUS_FILENAME
    data = read_json(path) or {}
    data.update({"last_verify_at": at.isoformat(), "last_verify_ok": ok, "last_verify_dump": dump})
    write_json_atomic(path, data)
