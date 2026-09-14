---
name: implement
description: Execute an approved exec-plan phase by phase — move it backlog/ → active/, run the repo check after every phase, tick criteria honestly, move it → completed/, then hand off to /review. Refuses a plan that still carries an open question. Use when the user says "implement this", "build this plan", "start coding", "execute the plan".
argument-hint: "<path under docs/exec-plans/, or the feature to implement>"
---

# Implement

Honour `.agents/skills/README.md`. You execute an **approved plan**. It was scoped by `/create-plan` — **follow it, do not redesign it.** Position: `/create-plan` → **`/implement`** → `/review` → `/open-pr`.

## Phase 0 — Plan and gate
1. Facts from `AGENTS.md`: `check`; plan states `backlog/ active/ completed/ superseded/`. A plan whose first phase creates the check runs it from that phase on.
2. Find the plan: a path → read fully; else list `backlog/` and `active/` — one match → read it, several → ask, none → `/create-plan`. Never write a plan from scratch here.
3. **Open-questions gate, before anything else:** `grep -c '^open_questions: none$' <plan>` must print `1`, and `grep -nEi 'open question|TBD|TODO\(decide\)|\?\?\?' <plan>` must print nothing. Any failure: say what and where, change nothing, point at `/create-plan <plan>` or `/grill-me`. No override.
4. Parse title, issue, phases, criteria. **Resume:** phases already `Done` in `active/` → continue at the first unfinished one.
5. Move `backlog/ → active/` with `git mv`, banner `⬜ BACKLOG` → `🚧 ACTIVE — started YYYY-MM-DD`, `status: active`, update the INDEX row. A second plan already active → say so and confirm.
6. Branch: `GH-<N>-<topic>` (or `<topic>`), from `main`, only if not already on it.
7. **Claim** (only when the plan names an issue): `gh issue edit <N> --repo mhmzdev/whatsapp-agent-relay --add-assignee @me`; set the board card to `In progress` (ids from `gh project field-list`). Another assignee already on it → stop and report.
8. Summarise scope; confirm before writing code.

## Phase 1 — Setup
Read the files the phase touches plus their nearest sibling that does the same kind of thing; that sibling is the convention. Match what is there.

## Phase 2 — The phase loop (one plan phase per pass)
1. Implement exactly the phase. Non-negotiables from `AGENTS.md`: read-only default with declared write paths; session control in the relay; dedup, offset after batch, backoff, dead-token exit, chunking; secrets only from the environment; nothing from the author's own setup (`.agents/rules/privacy.md`).
2. **Test.** Extend the repo check for the unit; a criterion without a test is not done.
3. **Validate.** Run the phase's `verify:` commands and the repo check. Everything green before recording.
4. **Record.** Set the phase `**Status:** Done` in the plan. One line on what changed.
5. **Advance** or, on the last phase, go to Phase 3.

Rules: plan order; only the current phase; no features beyond the plan. Ask only when genuinely stuck. Never accumulate a broken test.

## Phase 3 — Drive to green
Run every non-manual `verify:` until all pass, then the repo check. Present manual criteria as a checklist for the user (what to send from the phone, what to expect).

## Phase 4 — Finish
1. Move `active/ → completed/`, banner `✅ COMPLETED — YYYY-MM-DD`, `status: completed`, update the INDEX.
2. Hand off to **`/review`**. Do not open a PR unless asked.
3. Commit only when asked; stage by name; read the staged diff against the privacy rule. Commit messages end with the attribution trailer the repo uses (see `git log -3`).

## What NOT to do
- Redesign mid-build (stop and flag). Skip tests or the check. Leave the plan in `active/` after shipping. Move the card to Done. Commit or push unasked. Touch `.env`, a real `config.yaml`, or any real folder the relay would run over.
