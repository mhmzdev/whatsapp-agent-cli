---
type: Index
title: docs — the progressive-disclosure root
description: Start here for anything that is not code. Each directory below has its own INDEX.md; each artifact links to the ones before and after it in the lifecycle.
tags: [index, lifecycle]
timestamp: 2026-09-14T00:00:00Z
---

# docs

Reading order for the whole repo: [`AGENTS.md`](../AGENTS.md) → [`README.md`](../README.md) → this index → the artifact you need → the code.

Format: every document here is markdown with a small YAML frontmatter (`type` required; `title`, `description`, `tags`, `timestamp` when useful), following the Open Knowledge Format. Plain links between files are the graph. One slug travels every stage: `GH-<N>-<topic>` once an issue exists.

| Directory | Holds | Written by | Read by |
|---|---|---|---|
| [`brainstorm/`](brainstorm/INDEX.md) | WHAT and WHY, before any plan — approaches considered, the one leaned toward, open questions | `/brainstorm` | `/grill-me`, `/to-spec` |
| [`specs/`](specs/INDEX.md) | Numbered WHAT/WHY contracts. Temporary — once ticketed, the GitHub issue is the truth | `/to-spec` | `/file-an-issue`, `/create-plan` |
| [`exec-plans/`](exec-plans/INDEX.md) | HOW: phased, `file:line`-grounded plans with provable criteria, moving `backlog → active → completed` (or `superseded`) | `/create-plan`, moved by `/implement` | `/implement`, `/review`, `/open-pr` |
| `feat-checklist/` | Acceptance checklists per slug — created by the first `/review` | `/review` | `/open-pr` |

## Outside docs/

| File | Read it when |
|---|---|
| [`README.md`](../README.md) | you want the product definition and the feature list |
| [`.agents/rules/`](../.agents/rules/) | you are writing anything; today: [`privacy.md`](../.agents/rules/privacy.md) |
| [`.agents/skills/README.md`](../.agents/skills/README.md) | you are running a lifecycle skill or moving a board card |

Tickets are **GitHub issues** on [mhmzdev/whatsapp-agent-relay](https://github.com/mhmzdev/whatsapp-agent-relay/issues). There is no local ticket file, by design.
