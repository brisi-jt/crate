from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
