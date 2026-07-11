"""Backup bookkeeping — retention selection, manifest round-trip, status sidecar."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from crate.backup import (
    build_manifest,
    manifest_table_mismatches,
    read_backup_status,
    read_json,
    resolve_backup_dir,
    select_prunable,
    write_backup_status,
    write_json_atomic,
)
from crate.settings import Settings

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 11, 2, 30, 0)


def stamp(days_ago: int, hour: int = 2, minute: int = 30) -> tuple[str, datetime]:
    at = (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=minute)
    return at.strftime("%Y%m%dT%H%M%SZ") + ".sql.gz", at


def minute_entries(count: int) -> list[tuple[str, datetime]]:
    """``count`` dumps taken one minute apart, newest at NOW."""
    ats = [NOW - timedelta(minutes=i) for i in range(count)]
    return [(at.strftime("%Y%m%dT%H%M%SZ") + ".sql.gz", at) for at in ats]


# --- retention ---------------------------------------------------------------


def test_fewer_than_keep_last_dumps_are_all_retained() -> None:
    entries = [stamp(days_ago) for days_ago in range(5)]
    assert select_prunable(entries, now=NOW) == []


def test_only_newest_keep_last_survive_within_one_day() -> None:
    entries = minute_entries(40)
    prunable = select_prunable(entries, now=NOW, keep_last=30)
    oldest_ten = sorted(name for name, at in sorted(entries, key=lambda e: e[1])[:10])
    assert prunable == oldest_ten


def test_daily_keeper_survives_outside_newest_window() -> None:
    entries = minute_entries(30)
    old_name, old_at = stamp(10)
    entries.append((old_name, old_at))
    assert select_prunable(entries, now=NOW, keep_last=30) == []


def test_dumps_older_than_daily_window_are_pruned() -> None:
    entries = minute_entries(30)
    old_name, _old_at = stamp(20)
    entries.append((old_name, _old_at))
    assert select_prunable(entries, now=NOW, keep_last=30) == [old_name]


def test_daily_keeper_is_the_newest_dump_of_each_day() -> None:
    entries = minute_entries(30)
    morning_name, _ = stamp(10, hour=6, minute=0)
    evening_name, _ = stamp(10, hour=18, minute=0)
    entries += [stamp(10, hour=6, minute=0), stamp(10, hour=18, minute=0)]
    assert select_prunable(entries, now=NOW, keep_last=30) == [morning_name]
    assert evening_name not in select_prunable(entries, now=NOW, keep_last=30)


# --- manifest ----------------------------------------------------------------


def test_manifest_round_trips_through_disk(tmp_path: Path) -> None:
    manifest = build_manifest(
        database="crate",
        dump="20260711T023000Z.sql.gz",
        created_at=NOW,
        tables={"users": 14, "play_events": 1234, "tracks": 39704},
    )
    path = tmp_path / "20260711T023000Z.manifest.json"
    write_json_atomic(path, manifest)

    assert read_json(path) == manifest
    # Atomic write leaves no temp file behind.
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_read_json_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_json(tmp_path / "nope.json") is None


def test_manifest_mismatches_equal_counts() -> None:
    tables = {"users": 14, "tracks": 39704}
    assert manifest_table_mismatches(tables, dict(tables)) == []


def test_manifest_mismatches_reports_drift_missing_and_extra() -> None:
    expected = {"users": 14, "tracks": 39704, "gone": 1}
    actual = {"users": 15, "tracks": 39704, "surprise": 2}
    messages = "\n".join(manifest_table_mismatches(expected, actual))
    assert "users" in messages  # count drift
    assert "gone" in messages  # missing from restore
    assert "surprise" in messages  # unexpected in restore
    assert "tracks" not in messages


# --- status sidecar ------------------------------------------------------------


def test_status_missing_file_reads_as_unknown(tmp_path: Path) -> None:
    status = read_backup_status(tmp_path)
    assert status.last_backup_at is None
    assert status.backup_ok is None


def test_status_success_round_trip(tmp_path: Path) -> None:
    write_backup_status(tmp_path, ok=True, dump="20260711T023000Z.sql.gz", now=NOW)
    status = read_backup_status(tmp_path)
    assert status.backup_ok is True
    assert status.last_backup_at == NOW


def test_status_failure_preserves_last_success(tmp_path: Path) -> None:
    write_backup_status(tmp_path, ok=True, dump="20260711T023000Z.sql.gz", now=NOW)
    write_backup_status(tmp_path, ok=False, error="mysqldump exited 2", now=NOW + timedelta(days=1))
    status = read_backup_status(tmp_path)
    assert status.backup_ok is False
    assert status.last_backup_at == NOW  # last success survives the failed attempt


# --- directory resolution -------------------------------------------------------


def test_backup_dir_defaults_under_the_repo() -> None:
    settings = Settings(_env_file=None)  # ty: ignore[unknown-argument]
    resolved = resolve_backup_dir(settings)
    assert resolved.parts[-2:] == ("backups", "crate")


def test_backup_dir_setting_overrides_default(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, backup_dir=str(tmp_path))  # ty: ignore[unknown-argument]
    assert resolve_backup_dir(settings) == tmp_path
