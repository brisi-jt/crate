"""Application configuration.

All config and environment variables live here — nothing else in the codebase
reads the environment directly.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
