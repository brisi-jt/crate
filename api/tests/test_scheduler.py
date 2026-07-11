"""In-process scheduler — credential gating, log-once skips, tick timing."""

import logging
from datetime import datetime

import pytest
from sqlmodel import Session

from crate.model.enums import CredentialStatus
from crate.model.orm import SpotifyCredential, User
from crate.scheduler import (
    AccountScheduler,
    seconds_until_daily,
    seconds_until_monthly,
    seconds_until_weekly,
)
from crate.settings import Settings

pytestmark = pytest.mark.unit


class JobRecorder:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def __call__(self, session: Session, user: User) -> None:
        self.calls.append(user.id)


def make_scheduler(session: Session, job: JobRecorder) -> AccountScheduler:
    return AccountScheduler(
        session_factory=lambda: session,
        recent_job=job,
        nightly_job=job,
        top_job=job,
    )


def skip_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "crate.scheduler"]


async def test_pass_without_any_credential_logs_once_not_per_pass(
    session: Session, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    job = JobRecorder()
    scheduler = make_scheduler(session, job)

    with caplog.at_level(logging.INFO, logger="crate.scheduler"):
        await scheduler.run_recent_pass()
        await scheduler.run_recent_pass()
        await scheduler.run_recent_pass()

    assert job.calls == []
    assert len(skip_records(caplog)) == 1


async def test_pass_with_reauth_credential_skips_and_logs_once(
    session: Session, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    session.add(
        SpotifyCredential(
            user_id=user.id,
            refresh_token_encrypted="ct",
            status=CredentialStatus.needs_reauth,
        )
    )
    session.commit()
    job = JobRecorder()
    scheduler = make_scheduler(session, job)

    with caplog.at_level(logging.INFO, logger="crate.scheduler"):
        await scheduler.run_recent_pass()
        await scheduler.run_recent_pass()

    assert job.calls == []
    assert len(skip_records(caplog)) == 1


async def test_pass_with_active_credential_runs_job(session: Session, user: User) -> None:
    session.add(SpotifyCredential(user_id=user.id, refresh_token_encrypted="ct"))
    session.commit()
    job = JobRecorder()
    scheduler = make_scheduler(session, job)

    await scheduler.run_recent_pass()
    await scheduler.run_nightly_pass()
    await scheduler.run_top_pass()

    assert job.calls == [user.id, user.id, user.id]


async def test_skip_log_rearms_after_a_successful_run(
    session: Session, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    job = JobRecorder()
    scheduler = make_scheduler(session, job)

    with caplog.at_level(logging.INFO, logger="crate.scheduler"):
        await scheduler.run_recent_pass()  # logs the skip
        credential = SpotifyCredential(user_id=user.id, refresh_token_encrypted="ct")
        session.add(credential)
        session.commit()
        await scheduler.run_recent_pass()  # runs — re-arms the skip log
        credential.status = CredentialStatus.needs_reauth
        session.add(credential)
        session.commit()
        await scheduler.run_recent_pass()  # a fresh skip is worth a fresh line

    assert job.calls == [user.id]
    assert len(skip_records(caplog)) == 2


async def test_job_failure_is_contained_and_logged(
    session: Session, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    session.add(SpotifyCredential(user_id=user.id, refresh_token_encrypted="ct"))
    session.commit()

    async def broken_job(session: Session, user: User) -> None:
        raise RuntimeError("spotify fell over")

    scheduler = AccountScheduler(
        session_factory=lambda: session,
        recent_job=broken_job,
        nightly_job=broken_job,
        top_job=broken_job,
    )

    with caplog.at_level(logging.ERROR, logger="crate.scheduler"):
        await scheduler.run_recent_pass()  # must not raise

    assert any("spotify fell over" in (r.exc_text or "") for r in skip_records(caplog))


# --- weekly digest pass -----------------------------------------------------------


async def test_digest_pass_runs_without_a_spotify_credential(session: Session, user: User) -> None:
    """Digest generation is database-local — it must not gate on a credential."""
    job = JobRecorder()
    scheduler = AccountScheduler(
        session_factory=lambda: session,
        recent_job=job,
        nightly_job=job,
        top_job=job,
        digest_job=job,
    )

    await scheduler.run_digest_pass()

    assert job.calls == [user.id]


async def test_digest_pass_failure_is_contained(
    session: Session, user: User, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken_job(session: Session, user: User) -> None:
        raise RuntimeError("digest fell over")

    job = JobRecorder()
    scheduler = AccountScheduler(
        session_factory=lambda: session,
        recent_job=job,
        nightly_job=job,
        top_job=job,
        digest_job=broken_job,
    )

    with caplog.at_level(logging.ERROR, logger="crate.scheduler"):
        await scheduler.run_digest_pass()  # must not raise

    assert any("digest fell over" in (r.exc_text or "") for r in skip_records(caplog))


# --- tick timing ---------------------------------------------------------------


def test_seconds_until_daily_before_target() -> None:
    now = datetime(2026, 7, 12, 1, 0, 0)
    assert seconds_until_daily(now, hour=3) == 2 * 3600


def test_seconds_until_daily_after_target_rolls_to_tomorrow() -> None:
    now = datetime(2026, 7, 12, 4, 30, 0)
    assert seconds_until_daily(now, hour=3) == 22.5 * 3600


def test_seconds_until_monthly_before_target() -> None:
    now = datetime(2026, 7, 1, 2, 0, 0)
    assert seconds_until_monthly(now, day=1, hour=4) == 2 * 3600


def test_seconds_until_monthly_rolls_to_next_month() -> None:
    now = datetime(2026, 7, 12, 5, 0, 0)
    target_gap = datetime(2026, 8, 1, 4, 0, 0) - now
    assert seconds_until_monthly(now, day=1, hour=4) == target_gap.total_seconds()


def test_seconds_until_monthly_rolls_over_year_end() -> None:
    now = datetime(2026, 12, 15, 12, 0, 0)
    target_gap = datetime(2027, 1, 1, 4, 0, 0) - now
    assert seconds_until_monthly(now, day=1, hour=4) == target_gap.total_seconds()


def test_seconds_until_weekly_before_target() -> None:
    now = datetime(2026, 7, 6, 3, 0, 0)  # Monday 03:00
    assert seconds_until_weekly(now, weekday=0, hour=5) == 2 * 3600


def test_seconds_until_weekly_after_target_rolls_a_week() -> None:
    now = datetime(2026, 7, 6, 6, 0, 0)  # Monday 06:00 — past 05:00
    target_gap = datetime(2026, 7, 13, 5, 0, 0) - now
    assert seconds_until_weekly(now, weekday=0, hour=5) == target_gap.total_seconds()


def test_seconds_until_weekly_midweek() -> None:
    now = datetime(2026, 7, 9, 12, 0, 0)  # Thursday
    target_gap = datetime(2026, 7, 13, 5, 0, 0) - now
    assert seconds_until_weekly(now, weekday=0, hour=5) == target_gap.total_seconds()


# --- settings toggles ------------------------------------------------------------


def test_scheduler_settings_defaults() -> None:
    settings = Settings(_env_file=None)  # ty: ignore[unknown-argument]
    assert settings.scheduler_enabled is True
    assert settings.recent_plays_interval_minutes == 30
    assert settings.nightly_sync_hour == 3
    assert settings.top_items_day_of_month == 1
    assert settings.top_items_hour == 4
    assert settings.digest_weekday == 0
    assert settings.digest_hour == 5
