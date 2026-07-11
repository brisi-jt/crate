"""Shared column helpers for the ORM layer."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp — MySQL DATETIME columns carry no timezone."""
    return datetime.now(UTC).replace(tzinfo=None)


def enum_column(enum_cls: type[Enum], **kwargs: Any) -> Column:
    """VARCHAR-backed enum column (non-native, so new members need no migration)."""
    return Column(
        SAEnum(
            enum_cls,
            native_enum=False,
            length=32,
            values_callable=lambda e: [member.value for member in e],
        ),
        **kwargs,
    )


class TimestampedModel(SQLModel):
    """Base for every table: created_at/updated_at maintained automatically."""

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": utcnow},
    )
