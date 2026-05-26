# Hooten Young — Sales Backend

REST API for the Hooten Young sales + depletions domain. Ingests weekly QuickBooks "Sales by Product/Service Detail" exports and depletion pivots from HY's broker partner, normalizes them into a Postgres schema, and serves aggregated read endpoints consumed by the `hooten-young-dashboard` React UI.

One of three repos in the HY platform:
- **`hooten-young-sales`** — this repo. Sales + depletions backend (Python / FastAPI).
- **`hooten-young-marketing`** — marketing intelligence backend (separate team).
- **`hooten-young-dashboard`** — single React frontend that consumes both backends.

## Stack

Python 3.12 · uv · FastAPI · SQLAlchemy 2.0 (async) + asyncpg · Postgres (Cloud SQL) · openpyxl + pandas · GCP Cloud Run · GitHub Actions

## Quick start

```bash
# 1. Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync dependencies (creates .venv and installs runtime + dev deps)
uv sync

# 3. Copy env template and fill in values
cp .env.example .env.local

# 4. Run the API locally
uv run uvicorn hy_sales.main:app --reload --port 8000

# 5. Verify the smoke tests
uv run pytest -q
```

Hit `http://localhost:8000/health` to confirm the app is up. `GET /health/ready` additionally probes the database.

## Pre-commit

```bash
uv run ruff check . && \
uv run ruff format --check . && \
uv run mypy src && \
uv run pytest
```

Or wire in `pre-commit` (one-time):

```bash
uv run pre-commit install
```

## Repo guide

- [`CLAUDE.md`](./CLAUDE.md) — project context, conventions, design decisions. **Read this first.**
- [`db/migrations/`](./db/migrations/) — raw SQL schema migrations, executed manually against dev → prod.
- [`src/hy_sales/`](./src/hy_sales/) — application source.
  - `api/` — FastAPI routers.
  - `db/` — async engine + session.
  - `models/` — SQLAlchemy 2.0 ORM models (mirror the SQL schema; do not create / alter tables).
  - `parsers/` — xlsx parsers (broker-format-specific).
  - `schemas/` — Pydantic v2 request / response models.
  - `services/` — business logic and ingestion orchestration.
  - `settings.py` — pydantic-settings config.
  - `main.py` — FastAPI app entrypoint.
- [`tests/`](./tests/) — pytest suite (mirrors `src/`).
- [`.claude/`](./.claude/) — Claude Code config (agents, commands, skills).
- [`.mcp.json`](./.mcp.json) — MCP server wiring.

## Database

- **Schema:** `sales` (covers both sales and depletions domains; see `db/migrations/001_sales_schema.sql`).
- **Migrations:** raw SQL, hand-executed. No Alembic.
- **Source of truth:** the SQL files. ORM models mirror them but never run DDL.

## Deployment

Cloud Run, one service per environment in GCP project `hooten-young-platform`:

| Environment | Service               | Database          | Deploy trigger                          |
|-------------|-----------------------|-------------------|------------------------------------------|
| `dev`       | `hy-sales-api-dev`    | Cloud SQL `hy-dev`  | push to `main`                          |
| `prod`      | `hy-sales-api-prod`   | Cloud SQL `hy-prod` | tag `v*.*.*` + reviewer approval        |

GitHub Actions workflows in `.github/workflows/` (added later).

## Security

- **No secrets in code.** Service-account JSON keys, DB URLs, and API tokens must never be committed.
- **Sales data is sensitive commercial data.** Don't paste sample rows into public chat or issue trackers. Don't log raw row contents.
- **Internal use only.** Auth will be added before this API is exposed beyond HY infrastructure.
