# Installing & running crate locally

crate is a two-service app — a FastAPI backend (`api/`) and a Next.js frontend (`web/`) — backed by MySQL. This guide takes you from a clean clone to a running instance connected to your own Spotify library.

## Prerequisites

- **Docker** (for the local MySQL via `docker compose`)
- **[uv](https://docs.astral.sh/uv/)** — Python toolchain/runner for `api/`
- **[bun](https://bun.sh)** — package manager/runtime for `web/`
- A **Spotify account** and a **Spotify developer app** (free — set up below)

Ports used locally: API `:8200`, web `:3200`, MySQL `:3308`.

## 1. Create a Spotify developer app

crate connects to Spotify with the Authorization Code + **PKCE** flow, so you need a **Client ID** but **no client secret**.

1. Go to the **[Spotify Developer Dashboard](https://developer.spotify.com/dashboard)** → **Create app**.
2. In the app's **Settings**, copy the **Client ID**.
3. Under **Redirect URIs**, add exactly:
   ```
   http://127.0.0.1:8200/v1/auth/spotify/callback
   ```
   Use `127.0.0.1`, not `localhost` — Spotify requires the numeric loopback address for local redirect URIs (`127.0.0.1` is also exempt from Spotify's HTTPS-only rule, so plain `http` is fine here). The whole OAuth flow must stay on `127.0.0.1` so its state cookie survives the round-trip.
4. Save.

## 2. Configure the backend

The API reads all configuration from environment variables via a single settings module (`api/crate/settings.py`); every variable is documented in **`.env.example`**. Copy the values you need into `api/.env`:

```bash
cd api
cp ../.env.example .env    # then edit .env
```

At minimum set:

```bash
SPOTIFY_CLIENT_ID=<your-spotify-app-client-id>
```

Everything else has a working local default. Two you may want for local use:

- `CRATE_ENCRYPTION_KEY` — a Fernet key encrypting stored Spotify tokens. A development default is baked in so it works out of the box; set your own for anything beyond local experimentation.
- `CRATE_DEV_USER` — **local development only.** Setting it (to any id, e.g. `me`) attributes every request to that user and bypasses the hosted auth provider, so you can run crate locally without configuring one. Leave it unset in any deployed environment.

## 3. Start everything

```bash
# from the repo root — local MySQL
docker compose up -d db

# backend (:8200)
cd api
uv sync
CRATE_DEV_USER=me uv run uvicorn crate.app:app --reload --port 8200
# check: http://127.0.0.1:8200/healthz  → {"status":"ok"}

# frontend (:3200) — in a second shell
cd web
bun install
NEXT_PUBLIC_CRATE_AUTH=dev bun dev
```

`NEXT_PUBLIC_CRATE_AUTH=dev` runs the frontend against the dev-user auth provider, pairing with the API's `CRATE_DEV_USER` bypass so you can run locally without configuring Clerk. **This is required for local use unless you've set up Clerk** — otherwise the app defaults to Clerk mode (whenever a Clerk publishable key is present), which gates all data behind a Clerk session that a local run doesn't have.

Open **http://localhost:3200**. (The Spotify redirect URI stays on `127.0.0.1:8200` per Spotify's loopback rule — the OAuth round-trip runs against the API origin and is independent of the web page's origin.)

## 4. Connect Spotify and run the first sync

1. In the app, click **CONNECT** (top-left) → approve on Spotify's consent screen → you're redirected back and your credential is stored.
2. Run the first sync to pull your playlists onto the map. The library lands incrementally; enrichment (audio features, genres) fills in over subsequent passes from the open data sources.

## Troubleshooting

- **"client_id: Not present" when connecting** — `SPOTIFY_CLIENT_ID` isn't set in the API's environment. Confirm it's in `api/.env` (or pass it inline) and restart the API.
- **Reconnect fails with a state error / never returns** — the OAuth state cookie is origin-scoped, so the Spotify connect *and* callback must share one origin. Keep the redirect URI on `127.0.0.1:8200` (Spotify's loopback requirement); the app already starts the connect flow on that same `127.0.0.1:8200` API origin, so it round-trips cleanly regardless of whether you open the web app at `localhost` or `127.0.0.1`.
- **App stuck on "SYNC PASS RUNNING · PLAYLISTS INBOUND" with no data** — the frontend is in Clerk mode without a session (a Clerk key is present, or you're on an origin Clerk isn't configured for — e.g. `127.0.0.1` when Clerk allows only `localhost`), so every data query is gated off and nothing loads. Run the frontend with `NEXT_PUBLIC_CRATE_AUTH=dev` (see step 3) for local use.
- **Database won't start / port clash** — `:3308` is in use; stop the conflicting MySQL or change the compose port mapping.
- **Reset the database** — `docker compose down` keeps your data (the named volume survives). Never use `docker compose down -v` — that deletes the volume and your library with it.

## Checks (for contributors)

```bash
cd api && uv run pytest -m unit && uv run ruff check . && uv run ty check
cd web && bun run lint && bun run typecheck && bun run build
cd api && uv run pytest -m integration   # needs the compose database running
```

See **[docs/architecture.md](docs/architecture.md)** for how the taste engine works.
