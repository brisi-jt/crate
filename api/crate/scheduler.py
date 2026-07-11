"""In-process background scheduler for account-data capture.

Plain asyncio tasks started from the app's lifespan — no scheduler
dependency. Five loops, all on UTC clocks:

- recently-played capture every ``recent_plays_interval_minutes``
- saved-tracks diff + playlist sync nightly at ``nightly_sync_hour``
- top-items snapshots monthly on ``top_items_day_of_month`` at
  ``top_items_hour``
- weekly digest generation on ``digest_weekday`` at ``digest_hour``
- database backup nightly at ``backup_hour``:``backup_minute`` — deliberately
  before the nightly sync, so every day keeps a pre-mutation snapshot

The Spotify-backed passes skip quietly (one log line, re-armed after the next
success) while no usable credential exists, so a disconnected or
reauth-pending account never spams the log every tick. The digest pass reads
only local data, so it runs for every user regardless of credential state.
"""

import asyncio
import contextlib
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from crate.backup import resolve_backup_dir, write_backup_status
from crate.db import get_engine
from crate.errors import AppError
from crate.model.orm import SpotifyCredential, User, utcnow
from crate.services.account.wiring import (
    run_nightly_for_user,
    run_recent_plays_for_user,
    run_top_items_for_user,
)
from crate.services.digest.service import run_weekly_digest_for_user
from crate.settings import Settings, get_settings

logger = logging.getLogger(__name__)

JobFn = Callable[[Session, User], Awaitable[object]]

_BACKUP_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_db.py"


def seconds_until_daily(now: datetime, *, hour: int, minute: int = 0) -> float:
    """Seconds from ``now`` to the next occurrence of ``hour``:``minute`` UTC."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def seconds_until_weekly(now: datetime, *, weekday: int, hour: int) -> float:
    """Seconds from ``now`` to the next ``weekday`` (0 = Monday) at ``hour``:00 UTC."""
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    target += timedelta(days=(weekday - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return (target - now).total_seconds()


def seconds_until_monthly(now: datetime, *, day: int, hour: int) -> float:
    """Seconds from ``now`` to the next ``day``-of-month at ``hour``:00 UTC."""
    target = now.replace(day=day, hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)
    return (target - now).total_seconds()


def _default_session_factory() -> Session:
    return Session(get_engine())


async def run_backup_script() -> None:
    """Run scripts/backup_db.py in a subprocess with this interpreter.

    The script owns the dump, manifest, retention pruning, and the status
    sidecar; a non-zero exit surfaces here as an exception.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(_BACKUP_SCRIPT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    if process.returncode != 0:
        tail = output.decode(errors="replace")[-500:]
        raise RuntimeError(f"backup script exited {process.returncode}: {tail}")


class AccountScheduler:
    """Runs the account-data, digest, and backup jobs on their UTC clocks."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = _default_session_factory,
        recent_job: JobFn = run_recent_plays_for_user,
        nightly_job: JobFn = run_nightly_for_user,
        top_job: JobFn = run_top_items_for_user,
        digest_job: JobFn = run_weekly_digest_for_user,
        backup_job: Callable[[], Awaitable[None]] = run_backup_script,
        settings: Settings | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._recent_job = recent_job
        self._nightly_job = nightly_job
        self._top_job = top_job
        self._digest_job = digest_job
        self._backup_job = backup_job
        self._settings = settings or get_settings()
        self._sleep = sleep
        self._tasks: list[asyncio.Task[None]] = []
        # (job, user_id-or-None) keys whose skip has already been logged;
        # a successful run discards the key so a later regression logs again.
        self._skip_logged: set[tuple[str, int | None]] = set()

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._recent_loop(), name="crate-scheduler-recent"),
            asyncio.create_task(self._nightly_loop(), name="crate-scheduler-nightly"),
            asyncio.create_task(self._monthly_loop(), name="crate-scheduler-monthly"),
            asyncio.create_task(self._weekly_loop(), name="crate-scheduler-digest"),
        ]
        if self._settings.backup_enabled:
            self._tasks.append(
                asyncio.create_task(self._backup_loop(), name="crate-scheduler-backup")
            )
            logger.info(
                "nightly database backup armed for %02d:%02d UTC",
                self._settings.backup_hour,
                self._settings.backup_minute,
            )
        logger.info(
            "scheduler started: recent every %dmin, nightly %02d:00 UTC, "
            "monthly day %d %02d:00 UTC, digest weekday %d %02d:00 UTC",
            self._settings.recent_plays_interval_minutes,
            self._settings.nightly_sync_hour,
            self._settings.top_items_day_of_month,
            self._settings.top_items_hour,
            self._settings.digest_weekday,
            self._settings.digest_hour,
        )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    # -- loops ---------------------------------------------------------------

    async def _recent_loop(self) -> None:
        # Runs immediately on startup so a restart gap never outruns
        # Spotify's rolling 50-play window, then settles into the interval.
        while True:
            await self.run_recent_pass()
            await self._sleep(self._settings.recent_plays_interval_minutes * 60)

    async def _nightly_loop(self) -> None:
        while True:
            await self._sleep(seconds_until_daily(utcnow(), hour=self._settings.nightly_sync_hour))
            await self.run_nightly_pass()

    async def _monthly_loop(self) -> None:
        while True:
            await self._sleep(
                seconds_until_monthly(
                    utcnow(),
                    day=self._settings.top_items_day_of_month,
                    hour=self._settings.top_items_hour,
                )
            )
            await self.run_top_pass()

    async def _weekly_loop(self) -> None:
        while True:
            await self._sleep(
                seconds_until_weekly(
                    utcnow(),
                    weekday=self._settings.digest_weekday,
                    hour=self._settings.digest_hour,
                )
            )
            await self.run_digest_pass()

    async def _backup_loop(self) -> None:
        while True:
            await self._sleep(
                seconds_until_daily(
                    utcnow(),
                    hour=self._settings.backup_hour,
                    minute=self._settings.backup_minute,
                )
            )
            await self.run_backup_pass()

    # -- passes ---------------------------------------------------------------

    async def run_digest_pass(self) -> None:
        """Weekly digests for every user — local data only, no credential gate."""
        with self._session_factory() as session:
            for user in session.exec(select(User)).all():
                assert user.id is not None
                try:
                    await self._digest_job(session, user)
                except Exception:
                    logger.exception("weekly_digest failed for user %d", user.id)

    async def run_backup_pass(self) -> None:
        """Nightly database backup — one log line either way, failure never kills the loop."""
        try:
            await self._backup_job()
        except Exception as exc:
            logger.exception("database backup failed")
            # The script records its own failures; this covers the case where
            # it could not run at all, so /v1/sync/status still flips backup_ok.
            with contextlib.suppress(Exception):
                write_backup_status(resolve_backup_dir(self._settings), ok=False, error=str(exc))
        else:
            logger.info("database backup completed")

    async def run_recent_pass(self) -> None:
        await self._run_for_connected_users("recent_plays", self._recent_job)

    async def run_nightly_pass(self) -> None:
        await self._run_for_connected_users("nightly_sync", self._nightly_job)

    async def run_top_pass(self) -> None:
        await self._run_for_connected_users("top_items", self._top_job)

    # -- internals -------------------------------------------------------------

    def _log_skip(self, key: tuple[str, int | None], message: str, *args: object) -> None:
        if key in self._skip_logged:
            return
        self._skip_logged.add(key)
        logger.info(message, *args)

    async def _run_for_connected_users(self, job: str, fn: JobFn) -> None:
        with self._session_factory() as session:
            credentials = session.exec(select(SpotifyCredential)).all()
            if not credentials:
                self._log_skip(
                    (job, None),
                    "%s: no Spotify credential stored yet; skipping until one connects",
                    job,
                )
                return
            for credential in credentials:
                key = (job, credential.user_id)
                if credential.status.requires_reauth:
                    self._log_skip(
                        key,
                        "%s: credential for user %d needs re-auth; skipping until reconnected",
                        job,
                        credential.user_id,
                    )
                    continue
                user = session.get(User, credential.user_id)
                if user is None:
                    continue
                try:
                    await fn(session, user)
                except AppError as exc:
                    # The wiring's own credential gate (disconnected mid-pass,
                    # flipped to needs_reauth by the refresh) — same log-once
                    # treatment as the pre-checks above.
                    self._log_skip(
                        key, "%s: skipped for user %d: %s", job, credential.user_id, exc.title
                    )
                except Exception:
                    logger.exception("%s failed for user %d", job, credential.user_id)
                else:
                    self._skip_logged.discard(key)
                    self._skip_logged.discard((job, None))
