---
type: ExecPlan
slug: GH-14-error-docs
issue: 14
status: active
open_questions: none
---

# feat: error codes are documented and self-describing          🚧 ACTIVE — started 2026-09-17

## Problem

[#14](https://github.com/mhmzdev/whatsapp-agent-cli/issues/14). Eleven codes now carry the contract between this package and whoever calls it, and a user can reach none of them: a failure prints a sentence and exits 6, and nothing connects those to `platform_rejected`. The statuses live in a module docstring that someone who installed from PyPI has no reason to open. It blocks #8 on purpose — once scripts branch on published exit codes, the documented surface is expensive to change.

## Approach

Option 2 from the issue, plus option 3, which turned out to be a dozen lines: document the table, name the code in the output, and ship the table inside the tool.

**The code name reaches the user.** `error: the platform refused this request` becomes `error [platform_rejected]: the platform refused this request`. The token in brackets is what the document is keyed by and what a user can search for or quote in a bug report. The exit status is unchanged, so a script that already branches on numbers keeps working.

**`docs/errors.md` is the reference**, one row per code: name, exit status, what happened, what to do next. The "what to do" line is written by a human — that is the whole value — so the document is not generated. What is mechanical is that it stays complete, which the check enforces in both directions.

**`whatsapp-agent errors` prints the same table**, built from `CODES`, so the answer travels with the install. It also gives the check something to compare the document against from the outside.

**Retryable is the column that matters.** A caller's real question is "do I loop?": 7 yes, 4 and 6 never, the rest are usage or local problems. Each row says which, because that distinction is the one thing a script author has to get right.

## Success criteria

- [ ] Every code in `CODES` has a row in `docs/errors.md` with its exit status, and no row names a code that does not exist — `verify: python3 tests/smoke.py`
- [ ] A failure's first line names its code in brackets — `verify: python3 tests/smoke.py`
- [ ] `whatsapp-agent errors` prints every code, its exit status and whether retrying helps — `verify: python3 tests/smoke.py`
- [ ] The command's rows and the document's rows agree, code for code and status for status — `verify: python3 tests/smoke.py`
- [ ] Adding a code without documenting it fails the check, naming the code — `verify: manual 1. add a throwaway row to CODES 2. python3 tests/smoke.py fails naming it 3. remove it`
- [ ] The document says which codes are worth retrying and which never are — `verify: python3 tests/smoke.py` asserts every row carries a retry verdict
- [ ] The README points at it — `verify: grep -c "errors.md" README.md`
- [ ] Repo check passes on 3.10 through 3.13 — `verify: python3 tests/smoke.py` locally, the CI matrix on the PR

## Phases

### Phase 1 — The document and the command
**Status:** Not started
- Files: `docs/errors.md` (new), `whatsapp_agent/cli.py`, `README.md`
- Change: write the table, one row per code, with a human "what to do" and a retry verdict. Add an `errors` subcommand printing code, exit status, retry verdict and message from `CODES`. `_fail` gains the bracketed code. A pointer line in the README (which #3 rewrites wholesale).
- Test: Phase 2.

### Phase 2 — The check that keeps them honest
**Status:** Not started
- Files: `tests/smoke.py`
- Change: parse `docs/errors.md`, compare its code names and exit statuses against `CODES` in both directions, and compare the `errors` command's output against the document. Assert a failure line matches `error [<code>]:` and that every documented row carries a retry verdict.
- Test: the check itself; the manual criterion proves it fails when a code is undocumented.

## Risks

- **A table that rots anyway.** Only if someone edits the document and `CODES` in the same commit to agree wrongly; the check cannot catch a wrong sentence, only a missing or invented row.
- **Breaking a caller's parsing.** The bracketed code changes the first line's shape. Nothing has been published yet, which is exactly why this lands before #8.

## Out of scope

- Localisation: this is a developer tool in English. hisab's two-language rule is hisab's.
- Changing any exit status. The numbers are already a contract in the repo's own docs.
