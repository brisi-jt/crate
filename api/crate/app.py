import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session

from crate.db import get_engine
from crate.errors import (
    PROBLEM_MEDIA_TYPE,
    ProblemDetail,
    SafeJSONResponse,
    register_error_handlers,
)
from crate.router import (
    account,
    analytics,
    auth,
    competitive,
    digests,
    discovery,
    enrichment,
    history,
    insights,
    me,
    mutations,
    playlists,
    previews,
    radio,
    sync,
    triage,
)
from crate.scheduler import AccountScheduler
from crate.services import readiness
from crate.services.spill import reconcile_all_spills
from crate.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Drain any refresh tokens spilled to disk by a prior write failure
        # before anything else touches Spotify. Best-effort: a down DB here just
        # defers reconcile to the first healthy scheduler tick.
        with contextlib.suppress(Exception), Session(get_engine()) as session:
            reconcile_all_spills(session)
        scheduler = AccountScheduler() if settings.scheduler_enabled else None
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                await scheduler.stop()

    app = FastAPI(
        title="crate API",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=SafeJSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(sync.router)
    app.include_router(account.router)
    app.include_router(playlists.router)
    app.include_router(mutations.router)
    app.include_router(enrichment.router)
    app.include_router(analytics.router)
    app.include_router(discovery.router)
    app.include_router(digests.router)
    app.include_router(radio.router)
    app.include_router(previews.router)
    app.include_router(insights.router)
    app.include_router(me.router)
    app.include_router(triage.router)
    app.include_router(history.router)
    app.include_router(competitive.router)

    @app.get(
        "/healthz",
        tags=["ops"],
        summary="Liveness probe",
        description=(
            "Liveness only: returns ok whenever the process is running. It does "
            "NOT touch the database — use /readyz to learn whether the service "
            "can actually serve requests."
        ),
    )
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/readyz",
        tags=["ops"],
        summary="Readiness probe",
        description=(
            "Readiness: 200 only when the database round-trips a SELECT 1 within "
            "a short timeout and the applied migration revision matches the head "
            "the running code expects. Returns 503 problem+json naming the failed "
            "check otherwise. Unlike /healthz this exercises the database, so a "
            "down or drifted database is caught instead of reported healthy."
        ),
        responses={503: {"model": ProblemDetail, "description": "A readiness check failed."}},
    )
    def readyz() -> JSONResponse:
        report = readiness.evaluate_readiness()
        body: dict[str, object] = {
            "status": "ready" if report.ready else "not_ready",
            "checks": {check.name: check.ok for check in report.checks},
        }
        if report.ready:
            return JSONResponse(status_code=200, content=body)
        failed = report.failing()
        detail = (
            "; ".join(f"{c.name}: {c.detail}" for c in failed if c.detail)
            or "readiness check failed"
        )
        problem = ProblemDetail(
            title="Service not ready",
            status=503,
            detail=detail,
            error_code="NOT_READY",
        )
        return JSONResponse(
            status_code=503,
            content={**problem.model_dump(exclude_none=True), "checks": body["checks"]},
            media_type=PROBLEM_MEDIA_TYPE,
        )

    return app


app = create_app()
