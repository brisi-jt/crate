"""Application configuration.

All config and environment variables live here — nothing else in the codebase
reads the environment directly.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = "local"

    # Sync driver URL (pymysql) — Alembic uses it as-is. Compose MySQL listens
    # on host port 3308.
    database_url: str = "mysql+pymysql://crate:crate@127.0.0.1:3308/crate"

    # Origins allowed to call the API from a browser. The two vercel.app
    # entries are placeholders until the real project domains exist.
    cors_origins: list[str] = [
        "http://localhost:3200",
        "https://crate.vercel.app",
        "https://crate-web.vercel.app",
    ]

    # Fernet key encrypting stored Spotify tokens. The default only exists so
    # local development works out of the box — deployed environments must set
    # CRATE_ENCRYPTION_KEY to their own key (rotating it invalidates stored
    # credentials, which then need a reconnect).
    encryption_key: str = Field(
        default="aMel8p7-qylscKapRvm4wiNQZjEwHzj2UIfsbN_88Uw=",
        validation_alias="CRATE_ENCRYPTION_KEY",
    )

    # Local-development auth bypass: when set, every request is attributed to
    # the user with this clerk_user_id (created on first use). Unset in
    # deployed environments; Clerk JWT verification replaces the bypass.
    dev_user: str | None = Field(default=None, validation_alias="CRATE_DEV_USER")

    spotify_client_id: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8200/v1/auth/spotify/callback"

    # Playlist entry calls target /playlists/{id}/items (the current path)
    # when true, the deprecated /tracks alias when false. The client falls
    # back to the other path per playlist either way, so flipping this only
    # changes which path is tried first.
    spotify_use_items_endpoints: bool = True

    # Local-development stand-in for Spotify writes: when set, mutations skip
    # the real API entirely (invented ids/snapshots, local state still updated
    # and journaled). Never set in deployed environments.
    fake_spotify: bool = Field(default=False, validation_alias="CRATE_FAKE_SPOTIFY")

    # Last.fm API key for artist similarity and tags. Optional: without it the
    # enrichment pipeline skips Last.fm and reports that coverage as pending.
    lastfm_api_key: str | None = None

    # FreqBlog audio-features fallback. Optional; calls are metered against a
    # hard monthly allowance tracked in the freqblog_budget table.
    freqblog_api_key: str | None = None
    freqblog_monthly_budget: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
