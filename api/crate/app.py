from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crate.errors import register_error_handlers
from crate.router import (
    account,
    analytics,
    auth,
    digests,
    discovery,
    enrichment,
    mutations,
    playlists,
    radio,
    sync,
)
from crate.scheduler import AccountScheduler
from crate.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        scheduler = AccountScheduler() if settings.scheduler_enabled else None
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                await scheduler.stop()

    app = FastAPI(title="crate API", version="0.1.0", lifespan=lifespan)

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

    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
