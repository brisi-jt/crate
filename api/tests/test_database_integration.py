import pytest
from sqlalchemy import create_engine, text

from crate.settings import get_settings


@pytest.mark.integration
def test_database_reachable() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
