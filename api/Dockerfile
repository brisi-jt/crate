FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies first so code changes don't bust the layer cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY crate ./crate
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

# Railway injects PORT; default matches local convention.
CMD ["sh", "-c", "uv run --no-sync uvicorn crate.app:app --host 0.0.0.0 --port ${PORT:-8200}"]
