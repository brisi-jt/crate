"""The current-user profile: read the account, set the optional birth year.

Birth year is user-supplied (not from Spotify) and only personalizes the
taste-freeze reading — the insights survey renders fine without it. Kept
minimal: one GET, one PATCH.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from crate.deps import CurrentUserDep, SessionDep
from crate.errors import AppError, ProblemDetail

router = APIRouter(tags=["me"])

# Youngest plausible account age; a birth year later than this fails validation.
_MIN_AGE = 13
_MIN_BIRTH_YEAR = 1900


class HalLink(BaseModel):
    href: str


class MeResource(BaseModel):
    """The requesting account's profile."""

    id: int
    birth_year: int | None = Field(
        description="User-supplied birth year, personalizing the taste-freeze "
        "reading. Null until set."
    )
    links: dict[str, HalLink] = Field(serialization_alias="_links")


class MeUpdate(BaseModel):
    """Profile fields the account can change."""

    birth_year: int | None = Field(
        default=None,
        description="Birth year for the coming-of-age band; null clears it.",
    )


def _me_resource(user_id: int, birth_year: int | None) -> MeResource:
    return MeResource(
        id=user_id,
        birth_year=birth_year,
        links={
            "self": HalLink(href="/v1/me"),
            "insights": HalLink(href="/v1/insights"),
        },
    )


@router.get(
    "/v1/me",
    summary="Current account",
    description="The requesting account's profile, including the optional birth year.",
)
def get_me(user: CurrentUserDep) -> MeResource:
    assert user.id is not None
    return _me_resource(user.id, user.birth_year)


@router.patch(
    "/v1/me",
    summary="Update current account",
    description=(
        "Set or clear the account's birth year. A set year must be a plausible "
        "birth year — from 1900 to at least 13 years ago — so the taste-freeze "
        "coming-of-age band lands sensibly."
    ),
    responses={422: {"model": ProblemDetail, "description": "Implausible birth year."}},
)
def update_me(update: MeUpdate, session: SessionDep, user: CurrentUserDep) -> MeResource:
    assert user.id is not None
    if update.birth_year is not None:
        max_year = datetime.now(UTC).year - _MIN_AGE
        if not _MIN_BIRTH_YEAR <= update.birth_year <= max_year:
            raise AppError(
                422,
                "Implausible birth year",
                detail=f"birth_year must be between {_MIN_BIRTH_YEAR} and {max_year}.",
                error_code="INVALID_BIRTH_YEAR",
            )
    user.birth_year = update.birth_year
    session.add(user)
    session.commit()
    session.refresh(user)
    return _me_resource(user.id, user.birth_year)
