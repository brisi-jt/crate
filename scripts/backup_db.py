"""Logical backup of the live crate MySQL database (compose service ``db``).

Dumps the ``crate`` database with mysqldump (single-transaction, routines,
hex-blob), gzips it to ``backups/crate/<utc-timestamp>.sql.gz`` next to a
``<timestamp>.manifest.json`` of per-table row counts, prunes old dumps
(newest 30 kept, plus the newest per day for 14 days), and records the
outcome in ``backup_status.json`` — surfaced by ``GET /v1/sync/status``.

    cd api && uv run python ../scripts/backup_db.py            # dump + prune
    cd api && uv run python ../scripts/backup_db.py --verify   # check the newest dump

``--verify`` restores the newest dump into the isolated ``crate_test``
database only (the task-12 guard helpers enforce the ``*_test`` name before
anything destructive runs) and asserts the restored per-table row counts
match the dump's manifest. It never touches the live database. Don't run it
while ``pytest -m integration`` is using ``crate_test``.

Exits non-zero on any failure.
"""

import argparse
import gzip
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
sys.path.insert(0, str(API_DIR))  # make crate + tests importable from any cwd

from sqlalchemy import create_engine  # noqa: E402

from crate.backup import (  # noqa: E402
    TIMESTAMP_FORMAT,
    build_manifest,
    manifest_table_mismatches,
    read_json,
    record_verify,
    resolve_backup_dir,
    select_prunable,
    table_row_counts,
    write_backup_status,
    write_json_atomic,
)
from crate.model.orm import utcnow  # noqa: E402
from crate.settings import get_settings  # noqa: E402
from tests.db_guard import assert_test_database, derive_test_url, drop_all_tables  # noqa: E402

# Compose-local root credentials (docker-compose.yml); root is needed for
# --routines and for restoring into crate_test.
MYSQLDUMP_CMD = [
    *("docker", "compose", "exec", "-T", "db"),
    *("mysqldump", "-uroot", "-pcrate"),
    *("--single-transaction", "--routines", "--hex-blob"),
    # No --databases on purpose: the dump then carries no CREATE DATABASE/USE
    # statements, so a restore only ever lands in the schema named explicitly
    # on the mysql command line.
    "crate",
]


def manifest_path_for(dump_path: Path) -> Path:
    return dump_path.with_name(dump_path.name.replace(".sql.gz", ".manifest.json"))


def prune(backup_dir: Path) -> list[str]:
    entries: list[tuple[str, datetime]] = []
    for path in backup_dir.glob("*.sql.gz"):
        try:
            at = datetime.strptime(path.name.removesuffix(".sql.gz"), TIMESTAMP_FORMAT)
        except ValueError:
            continue  # not one of ours; leave it alone
        entries.append((path.name, at))
    prunable = select_prunable(entries, now=utcnow())
    for name in prunable:
        (backup_dir / name).unlink(missing_ok=True)
        manifest_path_for(backup_dir / name).unlink(missing_ok=True)
    return prunable


def run_backup() -> int:
    settings = get_settings()
    backup_dir = resolve_backup_dir(settings)
    backup_dir.mkdir(parents=True, exist_ok=True)
    started = utcnow()
    dump_path = backup_dir / f"{started.strftime(TIMESTAMP_FORMAT)}.sql.gz"

    try:
        # Row counts immediately before the dump; the manifest is the
        # restore-verify baseline. (Counts and dump are two snapshots moments
        # apart — a write landing in between shows up as a verify mismatch,
        # which is the loud-failure behaviour we want.)
        engine = create_engine(settings.database_url)
        try:
            counts = table_row_counts(engine)
        finally:
            engine.dispose()

        tmp = dump_path.with_name(f".{dump_path.name}.tmp")
        process = subprocess.Popen(
            MYSQLDUMP_CMD, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert process.stdout is not None and process.stderr is not None
        try:
            with gzip.open(tmp, "wb") as out:
                for chunk in iter(lambda: process.stdout.read(1 << 20), b""):
                    out.write(chunk)
            stderr = process.stderr.read()
            if process.wait() != 0:
                raise RuntimeError(
                    f"mysqldump exited {process.returncode}: "
                    f"{stderr.decode(errors='replace')[-500:]}"
                )
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(dump_path)

        write_json_atomic(
            manifest_path_for(dump_path),
            build_manifest(
                database="crate", dump=dump_path.name, created_at=started, tables=counts
            ),
        )
        write_backup_status(backup_dir, ok=True, dump=dump_path.name)
    except Exception as exc:
        write_backup_status(backup_dir, ok=False, error=str(exc))
        print(f"BACKUP FAILED: {exc}", file=sys.stderr)
        return 1

    size_kib = dump_path.stat().st_size // 1024
    print(
        f"Backed up crate -> {dump_path} "
        f"({size_kib} KiB gzipped, {len(counts)} tables, {sum(counts.values())} rows)."
    )
    pruned = prune(backup_dir)
    if pruned:
        print(f"Pruned {len(pruned)} old dump(s): {', '.join(pruned)}")
    return 0


def run_verify() -> int:
    settings = get_settings()
    backup_dir = resolve_backup_dir(settings)
    dumps = sorted(backup_dir.glob("*.sql.gz"))
    if not dumps:
        print(f"VERIFY FAILED: no dumps found in {backup_dir}", file=sys.stderr)
        return 1
    dump_path = dumps[-1]
    manifest = read_json(manifest_path_for(dump_path))
    if manifest is None:
        print(f"VERIFY FAILED: no manifest next to {dump_path.name}", file=sys.stderr)
        return 1

    # derive_test_url + assert_test_database guarantee the restore target is
    # crate_test — the same rails the integration suite runs on.
    test_url = derive_test_url(settings.database_url)
    engine = create_engine(test_url)
    try:
        assert_test_database(engine)
        drop_all_tables(engine)  # guarded: refuses anything not named *_test
        restore = subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "mysql", "-uroot", "-pcrate", str(test_url.database)],
            cwd=REPO_ROOT,
            input=gzip.decompress(dump_path.read_bytes()),
            capture_output=True,
        )
        if restore.returncode != 0:
            raise RuntimeError(
                f"restore into {test_url.database} exited {restore.returncode}: "
                f"{restore.stderr.decode(errors='replace')[-500:]}"
            )
        actual = table_row_counts(engine)
    except Exception as exc:
        record_verify(backup_dir, ok=False, dump=dump_path.name)
        print(f"VERIFY FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    mismatches = manifest_table_mismatches(manifest["tables"], actual)
    if mismatches:
        record_verify(backup_dir, ok=False, dump=dump_path.name)
        print(
            f"VERIFY FAILED: restore of {dump_path.name} into {test_url.database} "
            "does not match its manifest:",
            file=sys.stderr,
        )
        for message in mismatches:
            print(f"  - {message}", file=sys.stderr)
        return 1

    record_verify(backup_dir, ok=True, dump=dump_path.name)
    print(
        f"VERIFY OK: {dump_path.name} restored into `{test_url.database}`; "
        f"{len(actual)} tables, {sum(actual.values())} rows match the manifest."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="restore the newest dump into crate_test and compare row counts (no new dump)",
    )
    args = parser.parse_args()
    return run_verify() if args.verify else run_backup()


if __name__ == "__main__":
    sys.exit(main())
