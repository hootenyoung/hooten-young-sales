---
description: Run the code-reviewer subagent on current/staged Python changes
allowed-tools: Read, Bash, Glob, Grep
argument-hint: (optional) path or commit range to focus on
---

Invoke the `code-reviewer` subagent to review changes in this branch.

Default scope:

- Staged changes (`git diff --cached`)
- Unstaged changes (`git diff`)
- Recent commits on this branch not yet on `main` (`git log main..HEAD`)

If `$ARGUMENTS` is provided, narrow the review to that path or commit range.

The subagent should produce:

1. **Bugs** — likely defects, async/await mistakes, DB session lifecycle issues, pagination/rate-limit gaps, datetime/tz confusion.
2. **Type safety** — missing hints, unjustified `Any`, unannotated `# type: ignore`, generic misuse.
3. **Conventions** — Conventional Commits, naming, layout under `src/hy_analytics/`, ruff/mypy cleanliness.
4. **Security** — secrets, SQL injection, SSRF, pickle/eval, shell=True.
5. **Data sovereignty / compliance flags** — data exports, marketing-bound copy that needs the compliance-reviewer.
6. **Suggestions** — non-blocking improvements.

Group findings by severity (blocker / high / medium / nit).
