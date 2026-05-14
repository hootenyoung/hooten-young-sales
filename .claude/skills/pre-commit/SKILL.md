---
name: pre-commit
description: Run ruff + mypy + pytest before committing changes. Activate when the user says "ready to commit", "ship it", "let's commit", "before I push", or asks to verify the build is clean.
---

# pre-commit

Run the full pre-commit verification suite for Hooten Young Analytics: lint, format check, type check, tests.

## When to activate

- User signals they are about to commit, push, or merge.
- User asks "is it ready?", "did anything break?", "tests passing?".
- After completing a feature, before reporting it as done.

## Steps

Run these sequentially. Stop on first failure and report.

1. **Lint** — `uv run ruff check .`
   - If failures are auto-fixable, suggest `uv run ruff check --fix .` but do not run it without confirmation.
2. **Format** — `uv run ruff format --check .`
   - If formatting drift, suggest `uv run ruff format .`.
3. **Type check** — `uv run mypy src`
   - Type errors block the commit. Do not auto-suppress with `# type: ignore`.
4. **Tests** — `uv run pytest`
   - Use `-q` for terseness if output is huge.

## Reporting

- ✅ All four pass → confirm safe to commit.
- ⚠️ One or more fail → print the failing command's output verbatim, identify the root cause, and stop. Do **not** auto-fix without confirmation.

## Notes

- `uv run` resolves the project's virtual env automatically — no need to activate `.venv`.
- If `uv` itself isn't installed yet, prompt the user to install it (`curl -LsSf https://astral.sh/uv/install.sh | sh`) rather than falling back to bare `pip`.
- Long-running test suites: report progress every ~30s if it looks stuck.
