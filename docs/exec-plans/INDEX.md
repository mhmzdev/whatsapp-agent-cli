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
| [GH-5-recv](backlog/GH-5-recv.md) | Nothing can read what arrives: adds the long-poll, the cursor written only after a batch, dedup, backoff, and the creator record that retires `--to` | #4 (merged) |

## Active
| Plan | Started | Issue |
|---|---|---|

## Completed
| Plan | Shipped | Summary |
|---|---|---|
| [GH-4-send](completed/GH-4-send.md) | 2026-09-17 | `whatsapp-agent send` reaches the phone: rate limiter, HTTP layer mapping every response onto auth / rejected / unavailable, markdown conversion and `(i/n)` chunking, the message store, and `--dry-run` |
| [GH-2-package-skeleton](completed/GH-2-package-skeleton.md) | 2026-09-17 | `pip install -e .` gives a working `whatsapp-agent`: version from `pyproject.toml`, five failure codes with unique exit statuses, token from env then `--token-file`, state under XDG and never the cwd, every subcommand present as a stub exiting 5. `tests/smoke.py` is the repo check and CI is now enforcing |

## Superseded
| Plan | Superseded by |
|---|---|
