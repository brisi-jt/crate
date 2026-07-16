"""Storage-reachability check run before any refresh-token rotation.

Spotify rotates the refresh token whenever its token endpoint is hit, so a
refresh attempted while the database is unreachable can leave us holding a
rotated token we cannot persist — a permanently lost credential. ``ping_engine``
is the cheap gate that proves storage can serve a query before the refresh is
allowed to proceed. ``StorageUnavailable`` is deliberately its own class so no
caller ever mistakes a down database for a rejected credential (which would
wrongly force a re-auth).
"""

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


class StorageUnavailable(Exception):
    """The database could not be reached — skip this tick, never touch Spotify."""


def ping_engine(engine: Engine) -> None:
    """Raise ``StorageUnavailable`` unless the engine can serve ``SELECT 1``.

    The engine already carries ``pool_pre_ping``; this adds an explicit,
    caller-visible probe at the exact moment before a token rotation.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise StorageUnavailable(str(exc)) from exc
