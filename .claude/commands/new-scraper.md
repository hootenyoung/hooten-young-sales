---
description: Scaffold a new platform scraper module
allowed-tools: Read, Write, Edit, Glob, Grep
argument-hint: <platform name> (e.g. tiktok, reddit, youtube)
---

Activate the `new-scraper` skill and consult the `social-scraper` subagent to scaffold a new platform adapter under `src/hy_analytics/scrapers/`.

Steps:

1. Confirm the platform name from `$ARGUMENTS` (lowercase, snake_case).
2. Ask the `social-scraper` subagent which provider it recommends (Apify actor, official API, etc.) and why.
3. Scaffold:
   - `src/hy_analytics/scrapers/<platform>.py` — module with `Scraper` class and a typed `<Platform>Post` Pydantic model. Follow the standard scraper module shape documented in `.claude/agents/social-scraper.md`.
   - `tests/scrapers/test_<platform>.py` — placeholder test importing the module.
4. Report:
   - Files created.
   - Provider chosen + rationale.
   - Env vars the new scraper needs (so the user can add them to `.env.example`).
   - Known platform-specific gotchas to watch out for.

Do not implement the scraper logic itself in this scaffold — leave clearly-marked TODOs and a docstring pointing to the `social-scraper` agent for design guidance.
