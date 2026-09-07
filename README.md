# crate

**A taste engine for your Spotify library.** crate syncs your curated playlists into its own database, rebuilds the listening intelligence Spotify no longer exposes from open music data, and renders your whole library as an explorable map — with per-track triage, a suite of listening insights, and safe, reversible playlist edits.

Inspired by [Every Noise at Once](https://everynoise.com).

## What it is

- **A map of your taste.** Every track is embedded and laid out in 2-D, coloured by genre and clustered into the neighbourhoods your library actually forms — pan, zoom, and follow the structure.
- **Triage with evidence.** For each candidate, crate proposes where it belongs and *why*, citing named signals (audio-feature fit, genre adjacency, neighbour density, tempo/energy) rather than an opaque score.
- **Insights.** A suite of computed insights over structure, tempo, energy, era, and flow — the shape of a library, not just its contents.
- **Safe playlist edits.** Every mutation is journaled and reversible; bulk changes stage through a manifest → arm → commit flow with a single-click undo.
- **A discovery queue.** New candidates surface into a review queue you accept or reject, feeding the triage signals over time.

## Why the open stack

In 2026 Spotify withdrew the audio-features, recommendations, and related-artists endpoints for new apps and capped development-mode apps at five users. Rather than build on an API that can be revoked, crate derives all of its intelligence from open music data — **MusicBrainz, Last.fm, ReccoBeats, FreqBlog, Deezer previews, and Every Noise at Once** — and computes its own feature space from your library's own distribution. The constraint became the design: the engine is platform-independent and owns its data.

See the full attribution in [NOTICE.md](./NOTICE.md).

## Architecture

The interesting engineering, written up in **[docs/architecture.md](docs/architecture.md)**:

- **Percentile-space feature normalization** — features are scored against your library's own percentiles, so "high energy" means high *for you*, not against a defunct global scale.
- **Two-embedding split** — one UMAP embedding tuned for the *display* layout, a separate one for *clustering*, because a good picture and good clusters want different objectives.
- **Genre-blended distance** — track similarity blends acoustic distance with genre-space proximity.
- **Evidence-typed triage** — the suggester emits labelled evidence, not a black-box number.
- **Journaled writes with undo** — a mutation journal and a manifest/arm/commit protocol make bulk edits atomic and reversible.

## Stack

- **api/** — FastAPI + SQLModel + Alembic, managed with [uv](https://docs.astral.sh/uv/); RFC 7807 error bodies, HAL `_links`, `/healthz` + `/readyz`. Serves on `:8200`.
- **web/** — Next.js (App Router) + Tailwind v4 + shadcn/ui + TanStack Query + Zustand + `motion`, managed with [bun](https://bun.sh). Serves on `:3200`.
- **MySQL 8** via docker compose on `:3308` locally.
- **~950 backend tests and a ~220-file web test suite**, test-driven; manual, idempotent, batch-mode Alembic migrations with a nightly logical backup.

## Quickstart

Full setup — including the Spotify developer-app configuration — is in **[INSTALL.md](./INSTALL.md)**.

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

All configuration is documented in the root `.env.example`; copy the relevant blocks into `api/.env` and `web/.env.local`. A single settings module (`api/crate/settings.py`) reads the environment — nothing else does. A Spotify developer Client ID is required to connect a library; everything else has a working local default.

## Checks

```bash
cd api && uv run pytest -m unit && uv run ruff check . && uv run ty check
cd web && bun run lint && bun run typecheck && bun run build
cd api && uv run pytest -m integration   # needs the compose database
```

CI runs the same gates (`lint.yml`, `test.yml`, `test-integration.yml`) plus a monthly external-API contract probe (`contract-check.yml`).

## License

[MIT](./LICENSE) © 2026 James Towns. Third-party attribution in [NOTICE.md](./NOTICE.md).
