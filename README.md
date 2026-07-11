# crate

Personal Spotify playlist-intelligence tool, inspired by [Every Noise at Once](https://everynoise.com). Syncs a curated playlist library into its own database, enriches tracks and artists through open music-data APIs, computes structure/clustering/temporal/flow analytics, renders the library as an interactive graph, and supports playlist management with an undo journal plus a music-discovery review queue.

## Stack

- **api/** — FastAPI + SQLModel + Alembic, managed with [uv](https://docs.astral.sh/uv/). Serves on :8200.
- **web/** — Next.js (App Router) + Tailwind v4 + shadcn/ui + TanStack Query, managed with [bun](https://bun.sh). Serves on :3200.
- **MySQL 8** via docker compose on :3308 locally; Railway in production. Web deploys to Vercel.

## Quickstart

```bash
# database
docker compose up -d db

# api
cd api
uv sync
uv run uvicorn crate.app:app --reload --port 8200
# → http://localhost:8200/healthz

# web (separate shell)
cd web
bun install
bun dev
# → http://localhost:3200
```

Environment variables are documented in `.env.example` (copy the blocks into `api/.env` / `web/.env.local`).

## Checks

```bash
cd api && uv run pytest -m unit && uv run ruff check . && uv run ty check
cd web && bun run lint && bun run typecheck && bun run build
cd api && uv run pytest -m integration   # needs the compose database
```

CI runs the same gates: `lint.yml`, `test.yml`, and `test-integration.yml` (MySQL service container).

## Project tracking

Repo-local only: implementation plan in `thoughts/shared/plans/`, session ledger in `thoughts/ledgers/`.
