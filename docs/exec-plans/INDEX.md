---
type: Index
title: exec-plans
description: Implementation plans and where each one is in its life. A plan is a contract — no open questions — and moves between the four directories as work progresses.
tags: [index, plans]
timestamp: 2026-09-14T00:00:00Z
---

# exec-plans

Up: [docs/INDEX.md](../INDEX.md). Written by `/create-plan` into `backlog/`; `/implement` moves a plan to `active/` on start and `completed/` on finish; a plan overtaken by events goes to `superseded/` with a line saying by what.

## Backlog
| Plan | Problem it solves | Depends on |
|---|---|---|
| [GH-2-package-skeleton](backlog/GH-2-package-skeleton.md) | No package exists: makes `pip install -e .` produce a working `whatsapp-agent` that resolves its token and state dir, and creates the repo check every later ticket extends | nothing — everything in epic #1 depends on it |

## Active
| Plan | Started | Issue |
|---|---|---|

## Completed
| Plan | Shipped | Summary |
|---|---|---|

## Superseded
| Plan | Superseded by |
|---|---|
