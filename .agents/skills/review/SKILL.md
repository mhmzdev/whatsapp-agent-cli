---
name: review
description: Close a feature's inner loop — derive the acceptance checklist from intent plus diff, verify every criterion at the cheapest honest layer (repo check, terminal run, phone), check the relay's own conventions, and persist docs/feat-checklist/<slug>.md that /open-pr seeds the Test Plan from. Use when the user says "review this", "check before merging", "is this done".
argument-hint: optional plan path, issue number, or diff scope — defaults to the current branch diff
---

# Review

Honour `.agents/skills/README.md`. Position: `/implement` → **`/review`** → `/open-pr`. Two jobs: **is it done** (every criterion verified, honestly) and **is it right** (the relay's conventions). Advisory: report first, fix only when asked.

## Step 1 — Scope and intent
- Paths given → those. Else `git merge-base HEAD develop` → `git diff <base>...HEAD --name-only`. Announce the file count and areas.
- Find the intent: the plan for this slug in `docs/exec-plans/{active,completed}/`, its issue (`gh issue view`), the spec. The plan's criteria and the issue's `Done when` boxes seed the checklist; add what the diff shows the intent implies.

## Step 2 — Verify each criterion at the cheapest honest layer
- `[x]` — proven by a named command or test you ran this run.
- `[?]` — needs a human: a terminal run against a fake folder, or the phone. Write the exact steps.
- `[!]` — not done or broken. Say why with `file:line`.
Never tick on the user's behalf. Never mark `[x]` from reading code alone.

## Step 3 — Conventions checklist
- **Write boundary.** Can the agent write outside the declared write paths? Is a folder created after start denied? Does the deny still win over the folder's own agent settings?
- **Session control.** Reset and model choice handled in the relay without an agent call? A failed resume falls back to a new session?
- **Transport.** Dedup by message id; offset advanced only after the batch; backoff on 429/503; 409 logged as another poller; dead token exits; replies chunked under the cap; the agent's stdin closed.
- **Agent output.** Every text block kept, not only the final message?
- **Failures on the phone.** No raw stderr, path, token or HTTP body sent to the user unless the spec chose that on purpose.
- **Privacy.** `.agents/rules/privacy.md` over code, tests, docs, examples and commit messages. Example config names a fake project.
- **Tests.** Every new unit exercised in the repo check?
- **Docs.** README and `AGENTS.md` still true? Example config updated for any new key?

## Step 4 — Persist and report
Write `docs/feat-checklist/<slug>.md` (create `docs/feat-checklist/INDEX.md` if absent):

```markdown
# <slug> — acceptance checklist   (<n> proven · <n> manual · <n> failing)

- [x] <criterion> — `<check>` passes (test: <name>)
- [?] <criterion> — phone: send `…`, expect `…`
- [!] <criterion> — <why>, <file:line>

## Findings
FINDING-01 · Important · <file:line> — <what, and the rule it breaks>
```

Chat summary: path, counts, every `[!]` and Critical/Important finding verbatim. A clean review says so in one line.

## Step 5 — Act only when asked
Offer: fix the failing items · fix specific findings · hand off to `/open-pr` · stop. After a fix, re-run the check and report which ids changed.

## What NOT to do
- Fix before being asked. Tick manual items. Flag style you merely dislike (every finding maps to `AGENTS.md` or a rule). Expand past the scope.
