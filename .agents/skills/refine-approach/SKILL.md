---
name: refine-approach
description: Sharpen an existing relay brainstorm, spec or exec-plan in place — score it for clarity, completeness, specificity, YAGNI and scope, flag the one thing that hurts most, then improve it without adding scope. Use when the user says "refine this", "tighten the plan", "review the approach".
argument-hint: path to a doc in docs/brainstorm/, docs/specs/ or docs/exec-plans/
---

# Refine Approach

Honour `.agents/skills/README.md`. Improve a **thinking document** in place. Not a rewrite, not new scope.

## Step 1 — Get the doc
Path given → read it whole. Else list `docs/brainstorm/`, `docs/specs/`, `docs/exec-plans/{backlog,active}/` and ask which.

## Step 2 — Interrogate it (answer from the doc and the code, not the user)
- **Unclear** — a step a fresh agent would misread.
- **Unnecessary** — gold-plating, a hypothetical user, the relay growing a brain of its own.
- **Avoided** — a hard decision left implicit that `/implement` will trip over.
- **Assumed** — a CLI flag, an API behaviour or a hisab pattern claimed but not verified. Check it.
- **At risk** — write boundary, session control, offset and store, what reaches the phone on failure, privacy — under-treated?
- **Underestimated** — a phase that is really three.

## Step 3 — Score five criteria (Weak / OK / Strong, one line each)
Clarity · Completeness (plans: every criterion carries a `verify:`; `open_questions: none` true?) · Specificity (real `file:line`, real flags) · YAGNI · Scope (fits one PR?).

## Step 4 — Flag the one thing
The single issue that, unfixed, hurts most. Lead with it.

## Step 5 — Improve in place
Minor fixes → apply. Substantive (drop a requirement, restructure phases, split) → propose, get approval, apply. Preserve structure. Update the INDEX row if a plan's problem or dependencies changed.

## Step 6 — Hand off
Brainstorm → `/grill-me` then `/to-spec`. Spec → `/file-an-issue`, or `/create-plan` for one slice. Plan → `/implement`, or `/grill-me` for a last stress-test. After two passes, recommend stopping.

## What NOT to do
- Rewrite the document. Add requirements nobody discussed. Create a separate review file. Remove real constraints, rationale or open questions while simplifying. Resolve a question the doc reserves for the human.
