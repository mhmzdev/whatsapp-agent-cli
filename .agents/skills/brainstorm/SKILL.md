---
name: brainstorm
description: Explore WHAT to build for the relay and WHY through dialogue before any planning or code. Use when the user says "brainstorm", "let's explore", "think through this", or when a request is fuzzy enough that a plan would guess at scope. Produces docs/brainstorm/<slug>.md.
argument-hint: the feature or idea to explore
---

# Brainstorm

Honour `.agents/skills/README.md`. You are exploring an idea **before** it becomes a plan: nail down **WHAT** and **WHY**, not HOW. No code, no file lists, no phases.

```
/brainstorm → /grill-me → /to-spec → /file-an-issue → /create-plan → /implement → /review → /open-pr
  (what)       (harden)     (contract)   (slice)          (how)          (do)        (check)      (ship)
```

## Principles

1. **Ruthless YAGNI.** The relay is transport plus session control. The CLI agent is the brain; anything that makes the relay think, plan or keep its own model loop is out.
2. **The constraints are the product.** One WhatsApp agent, one creator, one folder, read-only by default, write paths declared. A feature that widens what the agent may touch without the config saying so is wrong; say so.
3. **One question at a time**, multiple choice, recommended default.
4. **Look before you ask.** `AGENTS.md`, `README.md`, the code, and hisab-whatsapp's transport (`hisab/wa.py`, `hisab/store.py`, `hisab/transcribe.py`) answer most transport questions.

## Flow

**Step 0 — Scope.** Which surface does the idea touch: transport (poll, send, media, rate limits), session control (reset, model, commands answered without the agent), the agent adapter (Claude Code, Codex, their flags and output parsing), the write boundary (deny list, config), transcription, the store, config, packaging and deploy, docs. A one-file fix → say so and recommend `/create-plan` or just doing it.

**Step 1 — Understand.** Light pass over the area. Then surface the real requirement one question at a time: who hits this and when, on the phone or at the server; the smallest version; what a WhatsApp gesture (a quoted reply, a voice note) could do instead of a command; what the write boundary must refuse. Explore 2–3 approaches, one line each with the trade-off, recommend one.

**Step 2 — Write** `docs/brainstorm/<slug>.md`, with frontmatter `type: Brainstorm`, and register it in `docs/brainstorm/INDEX.md`:

```markdown
# <Topic> — Brainstorm

## Problem
Who feels it, when, in user terms.

## Goal
The smallest outcome that counts.

## Approaches considered
1. **<Name>** — <one line>. Reuses <X>. Trade-off: <Y>.
**Leaning toward:** <which, why>.

## Surfaces touched
transport / session control / agent adapter / write boundary / transcription / store / config / deploy / docs

## Open questions
- [ ] ...

## Out of scope (YAGNI)
- ...
```

**Step 3 — Hand off.** Offer: **Grill it** (`/grill-me`, the usual next step) · **Spec it** (`/to-spec`) · **Plan it** (`/create-plan`, small low-risk ideas) · **Refine** (`/refine-approach`) · **Pause**.

## What NOT to do
- No phases, file lists or code. No invented requirements. No 400-line doc: if it is that big, split the idea. Nothing past the privacy rule.
