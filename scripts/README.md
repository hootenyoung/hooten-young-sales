# scripts/

Repo automation scripts — shell or Python — for one-off tasks that aren't part of the normal `uv` / `pytest` lifecycle.

## What lives here

- **Setup**: `setup.sh` — bootstrap a fresh clone (install uv if missing, `uv sync`, copy `.env.example`).
- **Deploy**: `deploy.sh` — wrap `gcloud run deploy` with project conventions (build args, secret bindings, region).
- **Data**: `seed.sh`, `migrate.sh` — DB seed / Alembic migration helpers.
- **Maintenance**: ad-hoc cleanup, log rotation, GCS bucket lifecycle audits, etc.

## Conventions

- One file per script, name = verb (`setup.sh`, `deploy.sh`, not `helper.sh`).
- Every shell script starts with `#!/usr/bin/env bash` + `set -euo pipefail`.
- Every Python script lives at `scripts/<name>.py` and runs as `uv run python scripts/<name>.py` — never `python scripts/...` directly.
- Document required env vars in a comment block at the top of every script.
- Make shell scripts executable: `chmod +x scripts/*.sh`.
- Add long-lived scripts to `pyproject.toml` `[project.scripts]` for discoverability via `uv run <name>`.

## Not here

- CI/CD workflow files — those live in `.github/workflows/`.
- App-level utilities — those live in `src/hy_analytics/utils/`.
- Alembic migration files — those live in `alembic/versions/` (when migrations land).
