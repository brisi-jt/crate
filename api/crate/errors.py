"""RFC 7807 problem-detail errors."""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemDetail(BaseModel):
    """Error body returned by every non-2xx response."""

    type: str = Field(default="about:blank", description="URI identifying the problem type.")
    title: str = Field(description="Short human-readable summary of the problem.")
    status: int = Field(description="HTTP status code.")
    detail: str | None = Field(default=None, description="Explanation specific to this occurrence.")
    error_code: str | None = Field(
        default=None, description="Stable machine-readable code, e.g. SPOTIFY_REAUTH_REQUIRED."
    )


class AppError(Exception):
    """Domain error rendered as an RFC 7807 response."""

    def __init__(
        self,
        status: int,
        title: str,
        *,
        detail: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.error_code = error_code

    def to_problem(self) -> ProblemDetail:
        return ProblemDetail(
            title=self.title, status=self.status, detail=self.detail, error_code=self.error_code
        )


def problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return problem_response(exc.to_problem())

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return problem_response(
            ProblemDetail(
                title=HTTPStatus(exc.status_code).phrase,
                status=exc.status_code,
                detail=str(exc.detail) if exc.detail else None,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else None
        detail = None
        if first:
            location = ".".join(str(part) for part in first.get("loc", []))
            detail = f"{location}: {first.get('msg', 'invalid value')}"
        return problem_response(
            ProblemDetail(
                title="Validation error",
                status=422,
                detail=detail,
                error_code="VALIDATION_ERROR",
            )
        )
