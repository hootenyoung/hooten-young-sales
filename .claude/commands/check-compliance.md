---
description: Run the compliance-reviewer subagent on selected text or a file
allowed-tools: Read, Glob, Grep
argument-hint: <file path | inline text to review>
---

Invoke the `compliance-reviewer` subagent to evaluate analytics-generated copy or recommendations against US alcohol marketing law.

Input handling:

- If `$ARGUMENTS` looks like a file path that exists, read the file and review its marketing-bound copy.
- Otherwise, treat `$ARGUMENTS` as inline text to review directly.
- If `$ARGUMENTS` is empty, review the current IDE selection (`<ide_selection>` context).

The subagent should evaluate against:

- **Federal (TTB)** — Trade Practices, prohibited statements (health claims, curative properties, false/misleading), required disclosures.
- **State restrictions** — flag states with stricter rules (e.g. UT, TX dry counties) when applicable.
- **Platform restrictions** — IG/TikTok community guidelines on alcohol promotion; youth-coded hashtags; consumption-pressure language.
- **Age-gating language** — confirm the copy presumes an age-gated context.
- **Responsibility messaging** — flag missing "drink responsibly" language where convention expects it.

Output:

- Verdict: ✅ compliant / ⚠️ revise / ❌ block
- Specific issues with quoted text and the rule that applies
- Suggested rewrites for any flagged passages
