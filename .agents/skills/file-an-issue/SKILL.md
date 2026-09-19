---
name: file-an-issue
description: File work as real GitHub issues on mhmzdev/whatsapp-agent-cli and its project board. Two modes — slice an approved spec into a parent issue plus tracer-bullet child sub-issues with native sub-issue and blocking edges, or file one standalone issue for a bug, chore or follow-up. Use when the user says "file an issue", "open an issue", "break this into tickets", "make tickets", "slice this up". Issues live on GitHub, never as local files.
argument-hint: "[path to spec | description of the one issue to file]"
---

# File an Issue

Honour `.agents/skills/README.md`. You file work as real **GitHub issues**. Nothing you produce is a local markdown file.

## Step 0 — Repo facts
From `AGENTS.md` → Repo facts: `issues_repo` (`mhmzdev/whatsapp-agent-cli`), `project_board`, `check`, labels (apply only what `gh label list --repo mhmzdev/whatsapp-agent-cli` returns; never create one). **If `project_board` is `undecided`:** ask once — reuse "Hisab Engineering" (`mhmzdev/projects/1`, with a way to tell relay cards apart) or create a new board — then write the answer into `AGENTS.md` before filing. Board prerequisite: `gh auth status` shows the `project` scope, else `gh auth refresh -s project` once.

## The title carries the topic
Every title becomes the downstream slug: `GH-<N>-<kebab-topic>`. `Quoted reply resolves after a reset` → `GH-4-quoted-reply-after-reset`. Avoid titles that are only a verb or only a component.

## Pick your mode

| Mode | When | Creates |
|---|---|---|
| **A — Spec breakdown** | An approved spec in `docs/specs/`, or "break this into tickets" | One **parent** + one **child** sub-issue per tracer-bullet slice, wired with sub-issue and `Blocked by` edges |
| **B — Standalone** | A bug, chore, follow-up or decision found mid-flight | **One** issue |

Ambiguous → ask. **Mode B and new capability:** if it introduces behaviour a user would have opinions about, plausibly needs more than one slice, or has a real fork in *what* to build, say so in one sentence and recommend `/to-spec` first. If they say file it, file it and note "filed without a spec" in the body.

---

# Mode A — Spec breakdown

Each ticket is a **tracer bullet**: cuts through every layer it needs (poll → store → agent call → reply), is independently demoable, fits one context window.

**A1 — Gather.** Read the spec and what it links. A `GH-<N>` in the spec filename means a parent exists — ask whether to add children rather than create a second parent.

**A2 — Light codebase pass (optional).** Spot prefactoring; give prefactors their own early ticket.

**A3 — Draft slices.** Observable behaviour, not layers ("a text sent from the phone comes back as the agent's reply, read-only", not "the poll part" then "the send part"). Prefactors first. Honest sizing: a new agent adapter is its own ticket; a new media type is one ticket.

**A4 — Approval gate.** Numbered list: **Title**, **Blocked by**, **Priority** (from the board's field), **What it delivers**. Ask: granularity right, edges real, merge or split? **Create nothing on GitHub until approved.**

**A5 — Create.** Run the privacy rule over every title and body first.
- **Parent**: title = spec title; body = Problem + Solution + Out of scope condensed, a `## Children` checklist (filled after), `Spec: docs/specs/<file>` (temporary). `gh issue create --repo mhmzdev/whatsapp-agent-cli --title … --body-file <tmp> [--label …]`. Parse the number.
- **Children**, in dependency order, body:

```markdown
**What to build:** the end-to-end behaviour, in observable terms — who sees it (phone / server log / terminal).

**Surfaces:** transport / session control / agent adapter / write boundary / transcription / store / config / deploy / docs.

**Blocked by:** #N, or "nothing".

## Done when
- [ ] <observable criterion>
- [ ] Repo check passes — `verify: <check from AGENTS.md>`
```
  Those boxes are what `/create-plan` mines for success criteria; write them provable.
- **Wire**: node ids via `gh issue view <N> --json id`; `gh api graphql` with `addSubIssue` (`issueId`: parent, `subIssueId`: child) and, for real dependencies, `addBlockedBy` (`issueId`: the blocked child, `blockingIssueId`: its blocker). If a mutation is refused, fall back to a `Blocked by #N` line and say so.
- **Board**: `gh project item-add <board> --owner mhmzdev --url <issue-url>` for parent and children; set Status `Todo` and Priority via `gh project item-edit` (ids from `gh project field-list <board> --owner mhmzdev --format json`; never hard-code). Never set In progress here.

**A6 — Mark the spec ticketed.** Frontmatter `status: ticketed`, add `parent: <url>`; update the INDEX row.

**A7 — Report.** Parent URL, every child URL, which start blocked. Offer `/create-plan <first unblocked>` and wait.

---

# Mode B — Standalone

1. Raise the spec question once (above).
2. **Ground it.** A reproduction, `file:line` for the mechanism read this run, `gh issue list --repo mhmzdev/whatsapp-agent-cli --state all --search "<keywords>"` for a sibling.
3. Body: `## What's wrong` (or `What's missing`) with the evidence · `## Why it matters` · `## Options` only for a real fork · `## Done when` with the same verify rule.
4. `gh issue create` → board item-add with Status `Todo` and a Priority. If an open parent covers the area, offer `addSubIssue` under it.
5. Report the URL, board status, parent (if any); offer `/create-plan` and wait.

## What NOT to do
- Create before the approval gate. Slice by layer. Invent labels, columns or ids. Circular or hand-wavy blocking edges. Oversize. Set In progress. Write issue files under `docs/`. Fabricate an issue number or `file:line`. Put anything from the author's own setup in a title or body.
