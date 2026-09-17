---
type: FeatChecklist
slug: GH-14-error-docs
issue: 14
timestamp: 2026-09-17T00:00:00Z
---

# GH-14-error-docs — acceptance checklist   (8 proven · 0 manual · 0 failing)

- [x] Every code in `CODES` has a documented row with its exit status, and no row names a code that does not exist — asserted in both directions in the check's "documented codes" section
- [x] **The check actually catches both mistakes** — proven this session by temporarily adding `throwaway_code` to `CODES` (the check failed naming it) and a `ghost_code` row to the document (the check failed naming that too). This was the plan's manual criterion; it was run rather than left for a human
- [x] A failure's first line names its code in brackets — `error [bad_usage]: …`, asserted for three different codes
- [x] `whatsapp-agent errors` prints every code, its exit status, whether retrying helps, and its message — run, and asserted row by row
- [x] The command's rows and the document's rows agree exactly — compared as sets; a mismatch prints the symmetric difference
- [x] Every row carries a retry verdict, and exactly one code is retryable — `platform_unavailable`; the check asserts the count, so a second one cannot be added silently
- [x] The README points at the table — asserted by the check, not by eye
- [x] Repo check passes — extended with the "documented codes" section

## Conventions

- **Failures are codes** — now visibly so. `detail:` remains the only place a platform body appears, and a traceback still needs `WHATSAPP_AGENT_DEBUG`.
- **No localisation** — this is a developer tool in English; hisab's two-language rule is hisab's.
- **No exit status changed.** The numbers were already a contract in the repo's docs; this publishes them.

## Findings

**FINDING-08 · Minor · `docs/errors.md`** — the check can prove a row exists and that its exit status and retry verdict are right. It cannot prove the "what to do" sentence is true. A wrong instruction would survive; only a reader catches that.

**FINDING-05 (from #5) — addressed in the document**, not in code: the `bad_usage` row says global options go before the subcommand. The full fix is the README rewrite in #3.
