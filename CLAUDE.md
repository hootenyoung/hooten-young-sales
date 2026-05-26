# Project: Hooten Young Sales Backend

## About Hooten Young

Hooten Young (HY) is a premium American spirits brand — whiskey and cigars, built around heritage, craft, and a masculine, military-adjacent identity. The HY platform spans three repos:

1. **`hooten-young-sales`** — this repo. Sales + depletions backend (Python / FastAPI).
2. **`hooten-young-marketing`** — marketing intelligence backend (separate team).
3. **`hooten-young-dashboard`** — single React frontend that consumes both backends.

Integration is at the system level (shared Postgres instances, shared GCP project) — not shared code. Each repo is self-contained.

## This Repo's Purpose

REST API for the sales + depletions domain. Concretely:

- **Ingestion.** Parse weekly xlsx feeds from HY's broker partner:
  - **Sales** — QuickBooks "Sales by Product/Service Detail" export.
  - **Depletions** — state × account × product × month pivot.
- **Normalize.** Map raw broker strings to canonical products / customers / accounts via alias tables. Store facts in long format (depletions) and as normalized headers + lines (sales).
- **Serve.** Read endpoints powering the dashboard — KPIs, monthly trends, breakdowns by product / state / distributor, white-space matrix, follow-up tracker.
- **Audit.** Every fact row references a `file_uploads` ledger entry. Re-ingesting a file is idempotent (SHA-256 dedup); corrected uploads upsert in place.

## Tech Stack

- **Language:** Python 3.12 (strict type hints; `mypy --strict`).
- **Package manager:** [uv](https://github.com/astral-sh/uv) (lockfile-based, fast).
- **API framework:** FastAPI (async).
- **DB:** Postgres (Cloud SQL). Schema: `sales`. Connection comes from `DATABASE_URL`.
- **ORM:** SQLAlchemy 2.0 async. Models mirror the SQL schema; we never create/alter tables from Python.
- **Migrations:** Raw SQL files in `db/migrations/`, executed manually. No Alembic.
- **Settings:** `pydantic-settings` (typed config from env vars).
- **Logging:** `structlog` (JSON-ready; Cloud Logging-friendly).
- **xlsx parsing:** `openpyxl` for raw cell access, `pandas` for the hierarchical QuickBooks layout.
- **Compute:** GCP Cloud Run (one service per environment).
- **Secrets:** GitHub Actions per-environment secrets in CI; `.env.local` locally.

## Architectural Decisions

- **Parser / model separation.** Parsers (`parsers/`) are broker-format-specific. They convert raw rows into a stable canonical model, which the services layer writes via ORM. If the broker changes the format, only the parser swaps.
- **Idempotent ingestion.** All fact tables have natural-key UNIQUE constraints; `file_uploads` dedups by SHA-256. Re-uploading the same file is a no-op; uploading a corrected file overwrites the affected rows.
- **Long-format facts.** Depletions are stored one row per (account, product, month) — never wide monthly columns.
- **Source-system namespacing.** `invoices` has `(source_system, invoice_ref)` as composite unique. If the broker changes and new invoice numbers collide with old ones, the two coexist cleanly.
- **Tunable values live in DB.** Business constants that may change (e.g. commission rate, currently flat 10%) live in `sales.app_config`, not Python constants. Update the row, no redeploy.
- **`updated_at` from ORM, not triggers.** Set on the column via `onupdate=func.now()`. No Postgres triggers.
- **`created_by` / `updated_by` deferred.** Will be added when user auth is integrated.

## Database

The schema source of truth is `db/migrations/001_sales_schema.sql`. ORM models in `src/hy_sales/models/` mirror these tables:

- `sales.file_uploads` — audit ledger for every uploaded file.
- `sales.app_config` — tunable business values.
- `sales.products`, `sales.product_aliases` — canonical SKUs + raw-string lookup.
- `sales.distributors`, `sales.customers`, `sales.customer_aliases` — 3-tier middle layer.
- `sales.accounts` — retail locations.
- `sales.invoices`, `sales.invoice_lines` — sales facts.
- `sales.depletions` — long-format depletion facts.

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
- **No `Co-Authored-By: Claude` lines** in commit messages.
- **Workflow:** Trunk-based. PRs into `main` → auto-deploy to dev. Tags `v*.*.*` → prod (with approval gate).
- **Type hints required** on every function signature.
- **Lint + format:** `ruff` (single tool, replaces flake8, isort, black).
- **Module layout:** all source under `src/hy_sales/`. No top-level scripts that import from `src/`.
- **Naming:** `snake_case` for modules / functions / variables; `PascalCase` for classes; `SCREAMING_SNAKE_CASE` for module constants.
- **Tests** live under `tests/`, mirroring `src/`. Use `pytest` + `pytest-asyncio`.

## Deployment

Cloud Run, one service per environment, in GCP project `hooten-young-platform`:

| Environment | Service              | Database          | Deploy trigger                            |
|-------------|----------------------|-------------------|--------------------------------------------|
| `dev`       | `hy-sales-api-dev`   | Cloud SQL `hy-dev`  | push to `main` (auto)                    |
| `prod`      | `hy-sales-api-prod`  | Cloud SQL `hy-prod` | tag `v*.*.*` + reviewer approval         |

GitHub Actions workflow in `.github/workflows/deploy.yml` (to be added). Auth to GCP via Workload Identity Federation — no long-lived service-account JSON keys.

## Security

- **No secrets in code.** Never commit API keys, tokens, DB URLs, or service-account JSON.
- **Sales data is sensitive commercial data.** Don't log raw rows. Don't paste sample data into public channels.
- **Internal use only.** Auth will be added before exposing this API beyond HY infrastructure.

## Pre-commit checklist

Before every commit:

1. `uv run ruff check .` — lint passes
2. `uv run ruff format --check .` — formatting passes
3. `uv run mypy src` — type-check passes
4. `uv run pytest` — tests pass

The `pre-commit` skill (`.claude/skills/pre-commit/`) automates this.
