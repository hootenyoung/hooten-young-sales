---
name: new-scraper
description: Scaffold a new social-platform scraper module under src/hy_analytics/scrapers/. Activate when the user asks to "add a scraper", "support TikTok/Reddit/etc.", or names a new platform to ingest from.
---

# new-scraper

Create a new platform scraper following Hooten Young Analytics conventions and the `social-scraper` subagent's design principles.

## When to activate

- User asks to add / create / scaffold a scraper for a specific platform.
- User says "let's start pulling X data" where X is a social platform.

## Before scaffolding — ask the social-scraper agent

The `social-scraper` subagent owns the design opinions: which provider (Apify actor, official API, third-party), what gotchas, what the normalized record shape should be. Consult it first; do not invent a design.

## Conventions to follow

1. **Location** — `src/hy_analytics/scrapers/<platform>.py`. One file per platform.
2. **Naming** — class `class <Platform>Scraper`, record model `class <Platform>Post(BaseModel)` (or `<Platform>Comment`, `<Platform>Account`, etc. as the data shape demands).
3. **Three-step separation** — `fetch()`, `parse()`, `persist()` are distinct functions. The scraper class wires them.
4. **Idempotent upserts** — use platform-native IDs as the unique key. Re-running a scraper does not create duplicates.
5. **Raw payload archival** — every fetch writes the raw provider response to GCS at `gs://<GCS_BUCKET_RAW_MEDIA>/<platform>/<account>/<timestamp>.json` before parsing. Re-parsing should not require re-fetching.
6. **Async + retry** — `async def fetch(...)` returns an `AsyncIterator`. Wrap network calls in `tenacity` with exponential backoff. Honor `Retry-After`.
7. **Provider interface** — implement the `ScraperProtocol` in `src/hy_analytics/scrapers/base.py` (create if it doesn't exist yet).
8. **Tests** — `tests/scrapers/test_<platform>.py` with at least a parse test using a checked-in raw-payload fixture.
9. **Env vars** — any new provider keys go into `.env.example` with documentation.
10. **Documentation** — add a section under External Integrations in `docs/architecture.md` describing the provider, legal basis, and rate limits.

## Steps

1. Confirm the platform name (lowercase, snake_case) and the data scope (posts only? posts + comments? accounts?).
2. Call out to the `social-scraper` subagent for design recommendation.
3. Scaffold the module file with the standard shape (see `.claude/agents/social-scraper.md`).
4. Scaffold the test file with a placeholder test.
5. Add required env vars to `.env.example`.
6. Update `docs/architecture.md` via `/sync-architecture`.
7. Report files created, env vars added, and the next implementation step (usually: write the fetch + parse, then the persistence layer).

## Do NOT

- Build headless-browser scraping into the ingestion path. Reserve Playwright for one-off inspection only.
- Hardcode credentials, even in tests. Use env vars + fixtures.
- Implement the full scraper in the scaffold — leave clearly-marked TODOs.
