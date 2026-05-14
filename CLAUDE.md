# Project: Hooten Young Analytics

## About Hooten Young

Hooten Young (HY) is a premium American spirits brand — whiskey and cigars, built around heritage, craft, and a masculine, military-adjacent identity. HY is building a proprietary AI marketing engine that spans **three separate repositories**, each owned independently but designed to integrate at the system level (shared database, shared APIs/buckets):

1. **`hooten-young-ui`** — public-facing website and consumer-facing content.
2. **`hooten-young-dashboard`** — internal weekly sales-review tool. Owned by another developer.
3. **`hooten-young-analytics`** — this repo. Social + competitor intelligence engine.

Integration between repos happens through shared infrastructure (Postgres DB, GCS buckets, APIs), not shared code. From Claude's perspective, each repo is self-contained.

## This Repo's Purpose

Ingests, normalizes, and analyzes multi-platform social data and competitor intelligence for the whiskey + cigar categories. The output — patterns, trends, gap analyses, winning creative formulas — is written to the shared Postgres database where the dashboard repo consumes it.

Concretely this repo does:

- **Ingestion.** Pull posts, engagement metadata, captions, media, and audio from social platforms (Instagram first; TikTok, Reddit, YouTube, X, Facebook later).
- **Storage.** Raw media to GCS, structured records to Postgres, embeddings to pgvector.
- **Analysis.** Pattern recognition over time-series engagement, hook detection, posting-time analysis, music/sound effect frequency, caption-length correlations.
- **Competitive intelligence.** Track competitor brands, identify positioning gaps and blind spots.
- **API.** A FastAPI surface for the dashboard to query insights, and for internal jobs to trigger work.

## Tech Stack

- **Language:** Python 3.12 (strict type hints required)
- **Package manager:** [uv](https://github.com/astral-sh/uv) (`pyproject.toml` + `uv.lock`)
- **API framework:** FastAPI (async)
- **Workers:** plain Python with `asyncio`. Long-running ingestion jobs may move to Pub/Sub later.
- **DB:** Postgres with the `pgvector` extension. Host is TBD (Cloud SQL or Neon) — connection comes from `DATABASE_URL`.
- **ORM:** SQLAlchemy 2.x (async) + Alembic for migrations.
- **Object storage:** GCS bucket for raw scraped media (video/image).
- **Compute (prod):** GCP Cloud Run, containerized.
- **Secrets (prod):** GCP Secret Manager. **Local dev:** `.env.local` (gitignored).
- **Scraping:** Third-party providers (Apify by default). Wrap behind a provider interface so we can swap.
- **AI:** Claude API for reasoning. Embeddings provider is env-var-driven (OpenAI or Vertex AI).

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
- **No `Co-Authored-By: Claude` lines** in commit messages.
- **Workflow:** PR-based; feature branches off `main`.
- **Type hints required** on every function signature (`mypy --strict` is the goal).
- **Lint + format:** `ruff` (replaces flake8, isort, black for our purposes).
- **Module layout:** all source under `src/hy_analytics/`. No top-level scripts that import from `src/`.
- **Naming:** `snake_case` for modules, functions, variables; `PascalCase` for classes; `SCREAMING_SNAKE_CASE` for module-level constants.
- **Tests** live in `tests/`, mirror the `src/` tree. Use `pytest` + `pytest-asyncio`.

## Architecture

See [docs/architecture.md](docs/architecture.md). That document is **maintained by the `architecture-updater` subagent** — run `/sync-architecture` after structural changes (new modules, new ingestion sources, new external integrations) to refresh it.

## Security & Compliance

- **Data sovereignty.** Per the HY SOW, **all ingested data, derived insights, and trained models are the sole property of Hooten Young.** This vendor may not reuse, repackage, or license any of it to third parties — particularly in spirits or tobacco. Be careful with how data is exported, logged, or shared.
- **Alcohol marketing law.** Any insight that bleeds into outward marketing (recommended copy, generated content, influencer scripts) must pass the `compliance-reviewer` subagent. US federal (TTB) and state rules apply.
- **No secrets in code.** Never commit API keys, tokens, database URLs, or service-account JSON. Use env vars locally; GCP Secret Manager in production. Service-account key files must never be committed.
- **Respect ToS and robots.txt** on every platform we scrape. Use third-party providers (Apify) where they have appropriate licenses. Document the legal basis for each new scraper in `docs/architecture.md` under External Integrations.
- **PII.** Captions and comments from public profiles are personal data. Do not log raw PII outside the database. Hash or pseudonymize user identifiers in analytics outputs where possible.

## Pre-commit checklist

Before every commit:

1. `uv run ruff check .` — lint passes (or `uv run ruff check --fix .` to auto-fix)
2. `uv run ruff format --check .` — formatting passes
3. `uv run mypy src` — type-check passes
4. `uv run pytest` — tests pass

The `pre-commit` skill (`.claude/skills/pre-commit/`) automates this. Invoke it before pushing.
