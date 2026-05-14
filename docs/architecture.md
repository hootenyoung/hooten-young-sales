# Architecture — Hooten Young Analytics

> **Maintained by `architecture-updater`.** Refresh this file via `/sync-architecture` after structural changes (new modules, new scrapers, new external integrations). Manual edits will survive but may be reconciled on the next run.

## Overview

`hooten-young-analytics` is the social + competitor intelligence engine for the Hooten Young AI marketing system. It is one of three repositories:

- `hooten-young-ui` — public-facing website.
- `hooten-young-dashboard` — internal weekly sales-review tool.
- `hooten-young-analytics` (this repo) — ingestion, normalization, pattern recognition, and competitive intelligence.

The engine produces structured insights to a shared Postgres database; the dashboard repo consumes those insights and presents them to HY leadership.

**Current state:** Pre-implementation. The Python project skeleton is in place — package layout, dependency manifest, placeholder modules — but no ingestion, parsing, persistence, or analysis is wired up yet. This document will fill in as the codebase grows.

**Planned stack:** Python 3.12 · uv · FastAPI · async SQLAlchemy + Postgres (pgvector) · GCS · GCP Cloud Run · Apify · Anthropic Claude.

## Folder Structure

```
hooten-young-analytics/
├── .claude/                 # Claude Code config: agents, commands, skills, settings
├── docs/                    # Architecture, onboarding
├── scripts/                 # Shell/Python automation (setup, deploy, data)
├── src/
│   └── hy_analytics/        # All application source under one package
│       ├── __init__.py
│       ├── api/             # FastAPI app + routes
│       ├── scrapers/        # Per-platform ingestion adapters
│       ├── models/          # SQLAlchemy ORM models
│       ├── services/        # Domain services (analysis, embeddings, ...)
│       └── utils/           # Shared helpers
├── tests/                   # Mirror of src/ layout
├── .env.example             # Env var template
├── .gitignore
├── .mcp.json                # MCP server config (github, postgres, playwright, filesystem)
├── .python-version          # 3.12 (uv/pyenv pick this up)
├── CLAUDE.md                # Repo-level Claude Code guidance
├── pyproject.toml           # Project + tool config (ruff, mypy, pytest)
└── README.md
```

## Ingestion Pipeline

_None yet — no scrapers implemented._

When scrapers are added, document for each platform:

- Provider (Apify actor / official API / other) and the legal basis for using it.
- Schedule and cadence (continuous, hourly, daily).
- Raw payload archival path in GCS.
- Normalized record shape (which fields land in which tables).
- Failure handling and retry policy.

Expected shape: `fetch → archive raw → parse → upsert → enqueue downstream (embeddings, analysis)`.

## Data Model

_None yet — no ORM models implemented._

When models are added, document:

- Top-level tables (accounts, posts, comments, embeddings, competitor_brands, insights).
- Relationships and foreign keys.
- pgvector columns and their dimensions.
- Indexes used for hot queries.
- Migration history (Alembic).

## External Integrations

_None wired yet. Anticipated:_

- **Postgres (shared with dashboard).** Connection via `DATABASE_URL`. Requires `pgvector` extension.
- **GCS bucket.** Raw scraped media (videos, images, thumbnails). Bucket name from `GCS_BUCKET_RAW_MEDIA`.
- **Apify.** Default scraping provider. Token from `APIFY_API_TOKEN`. Wrap behind `src/hy_analytics/scrapers/base.py` `ScraperProtocol` so providers are swappable.
- **Anthropic Claude.** Reasoning, pattern summarization, insight narration. Key from `ANTHROPIC_API_KEY`.
- **Embeddings provider.** OpenAI or Vertex AI, toggled by `EMBEDDINGS_PROVIDER`.
- **GCP Secret Manager.** Production secrets fetch. Local dev uses `.env.local`.

Update this section as each integration lands. Each entry should include: what it is, what module wires it up, which env vars it needs, and what fails when it's misconfigured.

## Deployment

_None yet — no Dockerfile, no Cloud Run config, no CI._

Planned:

- **Container.** Multi-stage Dockerfile with `uv` for dependency install. Image runs `uvicorn`.
- **Compute.** GCP Cloud Run service for the API. Cloud Run jobs (or Pub/Sub triggers) for scheduled ingestion.
- **Migrations.** Alembic runs at container start (or as a separate Cloud Run job before the API service rolls).
- **Secrets.** Mounted from GCP Secret Manager via Cloud Run env-from-secrets bindings.
- **CI.** GitHub Actions: ruff, mypy, pytest on every PR; build + deploy on merge to `main`.

Document the actual deployment shape here once provisioned (project ID, region, service names, IAM roles).
