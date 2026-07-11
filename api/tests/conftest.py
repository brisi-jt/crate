import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import crate.model.orm  # noqa: F401  — register all tables on SQLModel.metadata
from crate.model.orm import User


@pytest.fixture
def session():
    """In-memory SQLite session with the full schema — keeps unit tests offline."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def user(session: Session) -> User:
    row = User(clerk_user_id="test-user", spotify_user_id="spotify-jt")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
