---
name: to-spec
description: Turn a hardened discussion into a numbered written spec — a WHAT/WHY contract with problem, solution, user stories, decisions and testing seams — saved to docs/specs/<NNN>-<slug>.md and registered in its INDEX. Use when the user says "spec this out", "write this up as a spec", "make a spec". Synthesises the conversation; does not re-interview.
argument-hint: optional spec slug or brainstorm doc path
---

# To-Spec

Honour `.agents/skills/README.md`. Crystallise a discussion that already happened into a durable **spec**: the WHAT/WHY contract the rest of the lifecycle draws from. The HOW comes later.

```
/brainstorm → /grill-me → **/to-spec** → /file-an-issue → /create-plan → …
```

The next step is `/file-an-issue`, behind a **human gate**: present the spec, wait for approval.

**A spec is temporary; GitHub is the durable contract.** Once `/file-an-issue` runs, it copies Problem + Solution + Out of scope into the parent issue and links the children; from then on the issue is the source of truth (`status: ticketed`, frontmatter carries `parent:`). Never link into a spec from other docs; link to the issue.

## Step 0 — Do you have material?
If the WHAT is not settled (approaches still open, scope undefined, an open question the brainstorm reserved for the human still unanswered), **stop and recommend `/grill-me`.** A spec around an unresolved question gives the ambiguity a filename.

## Step 1 — Gather
The conversation is the primary source. Read `docs/brainstorm/<slug>.md` if it exists. Use the vocabulary from `AGENTS.md`: relay, CLI agent, WhatsApp agent, creator, folder, write path, session, store, reset.

## Step 2 — Testing seam (the one question you may ask)
Confirm where this is verified: the repo check (no network — the default, once it exists), a terminal run against a fake folder with a real CLI agent, or the phone against a demo WhatsApp agent. Prefer the highest seam that gives honest confidence.

## Step 3 — Number and write
`ls docs/specs/` → highest `NNN-` prefix + 1, zero-padded (`001` if empty). Write `docs/specs/<NNN>-<slug>.md`:

```markdown
---
type: Spec
slug: <slug>
status: draft
last_verified: <YYYY-MM-DD>
---

# <NNN> — <Feature> — Spec

## Problem
Who feels it, when, what it costs. No implementation.

## Solution
In plain terms. Still no implementation.

## User stories
1. As a <developer on their phone / person running the relay on a server / contributor adding an agent adapter>, I can <X> so that <benefit>.

## Decisions
Config shape, command set, store record, adapter seam, write-boundary rule — the clarifications the grilling produced. Which invariants it respects (read-only default, relay-owned session control, dedup, offset after batch, dead-token exit, privacy).

## Testing decisions
The seam(s) from Step 2 and the closest prior-art test to mirror.

## Out of scope
- <explicitly excluded>

## Further notes
- Open questions, links to the brainstorm doc.
```

## Step 4 — Register
Add a row to `docs/specs/INDEX.md` (`| [NNN](NNN-slug.md) | title | draft | date |`).

## Step 5 — Hand off (human gate)
Present the spec and wait. Offer: **Slice into issues** (`/file-an-issue`, expected) · **Plan it directly** (`/create-plan`, single-slice) · **Stop**.

## What NOT to do
- Interview the user (only the seam question). Bake in file paths or code that will go stale (a config schema or reply shape that *is* the decision is fine). Write the HOW. Invent a fact the discussion did not settle — flag it under Further notes.
