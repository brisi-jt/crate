"""M1: the scheduler's post-sync hook warms the analytics cache (track map).

run_nightly_for_user runs the saved-tracks diff + playlist sync, then rebuilds
the analytics cache so the expensive track-map projection is warm before any
read hits the 202 path. A recompute failure must never fail the nightly sync.
"""

import contextlib

import pytest
from sqlmodel import Session

import crate.services.account.wiring as wiring
from crate.model.orm import User

pytestmark = pytest.mark.unit


async def test_nightly_recomputes_analytics_after_sync(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    @contextlib.asynccontextmanager
    async def fake_client(_session, _user):
        yield object()

    async def fake_saved(_session, _client, _user):
        order.append("saved")

    async def fake_sync(_session, _user):
        order.append("sync")

    def fake_recompute(_session, _user, owned_only=True):
        order.append("recompute")
        return {"invalidated": 0, "computed": 0}

    monkeypatch.setattr(wiring, "spotify_client_for_user", fake_client)
    monkeypatch.setattr(wiring, "sync_saved_tracks", fake_saved)
    monkeypatch.setattr(wiring, "run_sync_for_user", fake_sync)
    monkeypatch.setattr(wiring, "recompute_all", fake_recompute)

    await wiring.run_nightly_for_user(session, user)

    # Recompute runs after the sync, warming the cache.
    assert order == ["saved", "sync", "recompute"]


async def test_nightly_recompute_failure_never_fails_the_sync(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextlib.asynccontextmanager
    async def fake_client(_session, _user):
        yield object()

    async def fake_saved(_session, _client, _user):
        pass

    async def fake_sync(_session, _user):
        pass

    def boom(_session, _user, owned_only=True):
        raise RuntimeError("recompute exploded")

    monkeypatch.setattr(wiring, "spotify_client_for_user", fake_client)
    monkeypatch.setattr(wiring, "sync_saved_tracks", fake_saved)
    monkeypatch.setattr(wiring, "run_sync_for_user", fake_sync)
    monkeypatch.setattr(wiring, "recompute_all", boom)

    # Must not raise — a warm-cache failure is best-effort.
    await wiring.run_nightly_for_user(session, user)
