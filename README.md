# Hooten Young Analytics

Social + competitor intelligence engine for **Hooten Young** — a premium American spirits brand (whiskey + cigars). This repo ingests multi-platform social data, runs pattern recognition over engagement and creative metadata, and writes structured insights to a shared Postgres database that the sibling `hooten-young-dashboard` repo consumes. One of three repos in the HY AI marketing engine; the others are `hooten-young-ui` (public website) and `hooten-young-dashboard` (internal weekly sales review).

## Stack

Python 3.12 · uv · FastAPI · async SQLAlchemy + Postgres (pgvector) · GCS · GCP Cloud Run · Apify · Anthropic Claude

## Quick start

```bash
# 1. Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync dependencies (creates .venv and installs runtime + dev deps)
uv sync

# 3. Copy env template and fill in values
cp .env.example .env.local

# 4. Run the API locally
uv run uvicorn hy_analytics.api:app --reload --port 8000

# 5. Run the smoke test
uv run pytest -q
```

## Pre-commit

```bash
uv run ruff check . && \
uv run ruff format --check . && \
uv run mypy src && \
uv run pytest
```

The `pre-commit` skill in `.claude/skills/pre-commit/` automates this.

## Repo guide

- [`CLAUDE.md`](./CLAUDE.md) — project context, conventions, compliance + data-sovereignty rules. Read this first.
- [`docs/architecture.md`](./docs/architecture.md) — current architecture (maintained by the `architecture-updater` subagent; refresh with `/sync-architecture`).
- [`docs/onboarding.md`](./docs/onboarding.md) — new-developer setup guide.
- [`.claude/`](./.claude/) — Claude Code config (hooks, agents, skills, slash commands).
- [`.mcp.json`](./.mcp.json) — MCP server wiring (GitHub, Postgres, Playwright, Filesystem).
- [`scripts/`](./scripts/) — automation scripts (setup, deploy, data).
- [`src/hy_analytics/`](./src/hy_analytics/) — application source (api, scrapers, models, services, utils).
- [`tests/`](./tests/) — pytest suite.

## Compliance + data sovereignty

Per the HY SOW, **all ingested data, derived insights, and trained models belong to Hooten Young.** The vendor cannot repackage or license any of this work product elsewhere. Be deliberate about exports, logs, and external sharing.

Any analytics output that bleeds into marketing (recommended copy, generated content, influencer scripts) must pass the `compliance-reviewer` subagent — US federal (TTB) and state alcohol-marketing rules apply. See [`CLAUDE.md`](./CLAUDE.md#security--compliance).
