---
name: create-plan
description: Turn a GitHub issue, spec, brainstorm or task description into a file:line-grounded implementation plan with phases and machine-checkable success criteria, written to docs/exec-plans/backlog/<slug>.md and registered in the INDEX. Use when the user says "create a plan", "plan this", "how should we build X". A plan carries no open question.
argument-hint: "<#N | issue URL | spec path | brainstorm path | task description>"
---

# Create Plan

Honour `.agents/skills/README.md`. You turn a WHAT into a HOW. Output is a **plan document**, precise enough that `/implement` executes it without re-deciding scope: exact paths, `file:line` anchors, the code shape where it is the decision, and criteria a command settles.

Position: `/file-an-issue` (or a picked issue) → **`/create-plan`** → `/implement` → `/review` → `/open-pr`. Input is normally one GitHub issue (one plan per issue); also a spec, brainstorm or bare description.

## Step 0 — Facts and naming
Repo facts from `AGENTS.md`: `check`, `docs/exec-plans/{backlog,active,completed,superseded}`, `issues_repo`, board. **If `check` is `none yet`,** the plan's first phase creates the check (a no-network regression script in the chosen language) and updates `check:` and the Commands table in `AGENTS.md`. Bare slug per Contract 2; no date prefix. No argument → ask for the issue, spec or task, then wait.

## Step 1 — Context
1. Read every mentioned file **fully**. Derive the slug and read any `docs/brainstorm/` or `docs/specs/` file for it first.
2. Issue given: `gh issue view <N> --repo mhmzdev/whatsapp-agent-relay --json title,body,url,labels,state,assignees`. It **is** the ticket: settled decisions from its body, its `Done when` boxes seed the criteria. Check blockers (`blockedBy` via `gh api graphql`); an open blocker → say so and stop unless told to plan ahead.
3. If the WHAT is still fuzzy or touches a risk area never grilled (the write boundary, session control, the offset and store, what reaches the phone on failure, anything privacy-adjacent), **recommend `/grill-me` first**.

## Step 2 — Targeted research
Grep/read **only** the areas the plan touches. For transport, read hisab-whatsapp's `hisab/wa.py` and `hisab/store.py` for prior art (copy through the privacy rule; do not import across repos). For the agent adapter, confirm the CLI's current non-interactive flags with `claude --help` / `codex --help` rather than memory. Note exact `file:line` anchors.

## Step 3 — Criteria (the contract)
Each criterion carries exactly one:
- `verify: <check from AGENTS.md>` — the repo check; every plan includes it.
- `verify: <command>` — another command whose exit 0 proves it.
- `verify: manual <numbered steps>` — a terminal run against a fake folder, or the phone against a demo WhatsApp agent; name what to send and the expected reply.
Rewrite anything vacuous into something provable.

## Step 4 — Write `docs/exec-plans/backlog/<slug>.md`

```markdown
---
type: ExecPlan
slug: <slug>
issue: <N or none>
status: backlog
open_questions: none
---

# <type>: <title>          ⬜ BACKLOG

## Problem
Why this exists. Link the issue / spec.

## Approach
The design in prose. Which existing pattern it reuses; which invariants it keeps (read-only default, relay-owned session control, dedup, offset after batch, dead-token exit, chunking, privacy).

## Success criteria
- [ ] <criterion> — `verify: …`
- [ ] Repo check passes — `verify: <check>`

## Phases
### Phase 1 — <name>
**Status:** Not started
- Files: (`file:line` anchors)
- Change: what, in enough detail that no decision remains
- Test: the assertion to add

### Phase 2 — …

## Risks
- ...

## Out of scope
- ...
```

Sizing: one phase ≈ one context window. The phone path is its own phase.

## Step 5 — Register and hand off
Add a row to `docs/exec-plans/INDEX.md` (Backlog table: file, problem, depends on). Then offer via one question: **Implement now** (`/implement`) · **Refine** (`/refine-approach`) · **Grill first** (`/grill-me`) · **Leave in backlog**.

## The no-open-questions contract
`open_questions: none` is a claim you make only when true. A fork the user has not decided goes back to `/grill-me`; it never ships inside a plan as "TBD".

## What NOT to do
- Write code. Put the plan anywhere but `backlog/`. Skip the INDEX row. Invent a criterion you cannot verify. Leave a question open.
