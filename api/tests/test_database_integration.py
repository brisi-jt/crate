import pytest
from sqlalchemy import Engine, text


@pytest.mark.integration
def test_database_reachable(integration_engine: Engine) -> None:
    with integration_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
