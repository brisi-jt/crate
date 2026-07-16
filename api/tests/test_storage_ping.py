"""Storage-reachability preflight — the gate before any token refresh.

The token endpoint rotates the refresh token on use; if we cannot store the
rotation the credential is lost. ``ping_engine`` proves the engine can serve a
trivial write-capable query before the refresh is allowed to proceed.
"""

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from crate.services.storage import StorageUnavailable, ping_engine

pytestmark = pytest.mark.unit


def _live_engine() -> Engine:
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def test_ping_healthy_engine_returns() -> None:
    ping_engine(_live_engine())  # no raise


def test_ping_unreachable_engine_raises_storage_unavailable() -> None:
    # A file engine pointed at an unwritable/nonexistent path fails at connect.
    engine = create_engine(
        "mysql+pymysql://x:x@127.0.0.1:1/nope", connect_args={"connect_timeout": 1}
    )
    with pytest.raises(StorageUnavailable):
        ping_engine(engine)


def test_storage_unavailable_is_not_a_credential_error() -> None:
    # It must be its own class so callers never confuse it with reauth.
    assert issubclass(StorageUnavailable, Exception)
    from crate.services.spotify.client import SpotifyReauthRequired

    assert not issubclass(StorageUnavailable, SpotifyReauthRequired)
