# Onboarding — Hooten Young Analytics

Welcome. This is the social + competitor intelligence engine for Hooten Young. It is one of three repos in the HY system; see [CLAUDE.md](../CLAUDE.md) for the big picture.

## Before you start

You'll need:

- **Python 3.12** — version pinned in `.python-version`. Install via `pyenv` or rely on `uv`'s managed Python.
- **uv** — modern Python package manager. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Docker** — for local Postgres and (later) building Cloud Run images.
- **GCP access** — read access to the HY analytics project. Ask the project lead for an invite.
- **GitHub access** — write access to `hooten-young-analytics`.
- **Claude Code** — recommended. The repo has `.claude/` configured with subagents, slash commands, and skills tailored for this repo.

## First-time setup

```bash
git clone https://github.com/hootenyoung/hooten-young-analytics.git
cd hooten-young-analytics

# Sync dependencies (creates .venv automatically)
uv sync

# Copy env template and fill in values (see Environment vars below)
cp .env.example .env.local

# Run the smoke test to confirm the install works
uv run pytest -q

# Run the API locally
uv run uvicorn hy_analytics.api:app --reload --port 8000
```

Open http://localhost:8000/docs for the auto-generated OpenAPI UI.

## Environment vars

All env vars live in `.env.local` for development and **GCP Secret Manager** in production. Never commit `.env*` files. See `.env.example` for the current list and what each var is for.

Critical vars to set before anything works:

- `DATABASE_URL` — async Postgres connection.
- `GCP_PROJECT_ID`, `GCP_REGION`, `GCS_BUCKET_RAW_MEDIA` — GCP infra.
- `APIFY_API_TOKEN` — scraping provider.
- `ANTHROPIC_API_KEY` — Claude API.

## Running a scraper

_(Not implemented yet.)_ Once scrapers land, the pattern will be:

```bash
# Run a one-off ingestion for a single account
uv run python -m hy_analytics.scrapers.run --platform instagram --handle <handle>

# Or trigger via the API
curl -X POST http://localhost:8000/ingest/instagram \
  -H 'Content-Type: application/json' \
  -d '{"handles": ["..."]}'
```

## Running tests

```bash
uv run pytest                # full suite
uv run pytest tests/scrapers # one subtree
uv run pytest -k smoke       # by keyword
uv run pytest --cov=hy_analytics  # with coverage
```

## Daily workflow

1. Pull `main`, branch off (`git checkout -b feat/your-thing`).
2. Make changes. Run the `new-endpoint` or `new-scraper` skill when adding a route or a platform adapter so the structure stays consistent.
3. Use `/review` to invoke the code-reviewer subagent before opening a PR.
4. If any output is intended for marketing use (copy, recommendations, scripts), run `/check-compliance <file>` against the compliance-reviewer.
5. Run the pre-commit skill: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`.
6. Commit with [Conventional Commits](https://www.conventionalcommits.org/) format — `feat:`, `fix:`, `chore:`, etc. **No `Co-Authored-By: Claude` lines.**
7. Open a PR. CI will run the same checks.

## What's in `.claude/`

- **`agents/`** — subagents specialized for this repo:
  - `architecture-updater` — refreshes `docs/architecture.md` via `/sync-architecture`.
  - `code-reviewer` — Python-focused review (async/await, types, DB sessions, security).
  - `compliance-reviewer` — US alcohol marketing law (TTB + state + platform rules).
  - `social-scraper` — scraping design, ToS, rate limits, Apify usage, IG quirks.
  - `trend-analyst` — engagement pattern analysis with statistical rigor.
  - `competitor-researcher` — gap analysis for whiskey + cigar competitors.
  - `data-quality-auditor` — audits ingested rows for completeness, duplicates, drift, suspicious values.
- **`commands/`** — slash commands: `/review`, `/check-compliance`, `/sync-architecture`, `/new-scraper`.
- **`skills/`** — `new-endpoint`, `new-scraper`, `pre-commit`.
- **`settings.json`** — safe Stop hook (timestamps a session log); PreToolUse hook that blocks destructive bash commands.

When in doubt, ask Claude — it has the repo's conventions in context via [CLAUDE.md](../CLAUDE.md).

## Compliance + data sovereignty — read this once

Hooten Young is a regulated alcohol brand, and per the SOW **all data and insights produced here belong to HY** — the vendor cannot reuse or license them elsewhere.

- Run any marketing-bound output through `/check-compliance`.
- No health claims, no minor-targeted language, no false statements about strength/origin/age.
- Be deliberate about exports, logs, and external sharing. Don't pipe HY data to third-party tools without confirming licensing.
- Service-account JSON files and `.env*` files are gitignored — keep it that way.

When in doubt, flag it for a human (legal / project lead) review.

## Who owns what

- **`hooten-young-ui`** — public website. Different developer focus.
- **`hooten-young-dashboard`** — sales review tool. Different developer; ask the project lead for the contact.
- **`hooten-young-analytics`** — this repo.

Cross-repo work usually means coordinating at the database/API layer, not the code layer. The schema in shared Postgres is owned here; the dashboard consumes it read-only (mostly). Coordinate schema changes via PR + ping the dashboard owner.

## Helpful pointers

- Architecture: [architecture.md](architecture.md) (maintained by the `architecture-updater` agent).
- Scraper design opinions: `.claude/agents/social-scraper.md`.
- Compliance rules summary: `.claude/agents/compliance-reviewer.md`.
- Project SOW (high-level scope, deliverables, IP terms) — ask the project lead.
