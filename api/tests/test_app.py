import pytest
from fastapi.testclient import TestClient

from crate.app import create_app
from crate.settings import Settings


@pytest.mark.unit
def test_healthz_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.unit
def test_settings_defaults() -> None:
    # _env_file=None keeps the test hermetic if a local .env exists.
    settings = Settings(_env_file=None)  # ty: ignore[unknown-argument]
    assert settings.app_env == "local"
    assert settings.database_url.startswith("mysql+pymysql://")
    assert "http://localhost:3200" in settings.cors_origins


@pytest.mark.unit
def test_cors_allows_web_origin() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz", headers={"Origin": "http://localhost:3200"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3200"
