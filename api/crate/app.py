from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crate.errors import register_error_handlers
from crate.router import analytics, auth, enrichment, playlists, sync
from crate.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="crate API", version="0.1.0")

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
    app.include_router(playlists.router)
    app.include_router(enrichment.router)
    app.include_router(analytics.router)

    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
