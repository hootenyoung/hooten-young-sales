---
description: Manually trigger a refresh of docs/architecture.md
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
argument-hint: (optional) area of the codebase to focus on
---

Invoke the `architecture-updater` subagent to regenerate `docs/architecture.md` for this repo.

Instructions for the subagent:

- Scan the current state of the repository (folder structure, source modules, scraper adapters, data models, external integrations, deployment surface).
- Compare against the existing `docs/architecture.md`.
- Rewrite the file so its six sections (Overview, Folder Structure, Ingestion Pipeline, Data Model, External Integrations, Deployment) reflect the **current** state of the code — not historical or aspirational state.
- Keep the maintained banner at the top of the file.
- If `$ARGUMENTS` is provided, focus the refresh on that area (e.g. `scrapers/`, `models/`, a specific platform).

After regeneration, print a brief diff summary of what changed.
