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

## Active
| Plan | Started | Issue |
|---|---|---|

## Completed
| Plan | Shipped | Summary |
|---|---|---|
| [GH-20-offline-transcription](completed/GH-20-offline-transcription.md) | 2026-09-19 | `--provider local` runs Whisper offline through the opt-in `wa-agent[local]` extra: no key, no network; models come only from an explicit `model pull` that says its size first, never during `recv`; a local transcript is tagged `transcribed_by` and the docs say plainly it is weak on Urdu and code-switching; new code `local_not_ready` (16); doctor gains a `local engine` line; the real download and a real note are left unticked as a post-merge step for the owner and lead |
| [GH-32-doctor](completed/GH-32-doctor.md) | 2026-09-19 | `wa-agent doctor` checks a setup one line at a time (python, token, Gemini key, OpenRouter key, state dir, creator) without polling, so it cannot steal a running `recv`'s long-poll; exit `doctor_failed` (15); the live probe mappings are left unticked as post-merge steps for the owner and lead |
| [GH-33-openrouter-transcription](completed/GH-33-openrouter-transcription.md) | 2026-09-19 | OpenRouter joins Gemini as an explicit second transcription provider: `--provider` on `transcribe` and `recv`, default `gemini` and never guessed from a key, per-provider key and model defaults, `no_transcription_key` made provider-neutral; the live confirmation is left unticked as a post-merge step for the owner and lead |
| [GH-7-transcribe](completed/GH-7-transcribe.md) | 2026-09-18 | Gemini transcription over plain HTTP with no SDK and no extra: `transcribe <file>`, `recv --transcribe` folding words into a voice note without changing its shape, three codes (12 no key, 13 unreachable, 14 nothing usable), and audio deleted the moment it is transcribed |
| [GH-14-error-docs](completed/GH-14-error-docs.md) | 2026-09-17 | Failures name their code (`error [platform_rejected]: …`), `docs/errors.md` gives each one a what-to-do and a retry verdict, `whatsapp-agent errors` ships the same table, and the check compares all three so a code cannot stay undocumented |
| [GH-6-media](completed/GH-6-media.md) | 2026-09-17 | `media get` and `media put` with both hops checked, mime-prefix extensions, per-type size caps refused locally, and a sweep that only touches our own directory; `send --file` and `send --media` attach, photos as images and everything else as named documents |
| [GH-5-recv](completed/GH-5-recv.md) | 2026-09-17 | `whatsapp-agent recv` reads what arrives: long-poll with the cursor written only after a batch, dedup by message id, JSON or human output, `--follow` with exponential backoff, `--typing`, `--replay`, a 409 exiting 9, and the creator record that retires `--to` on `send` |
| [GH-4-send](completed/GH-4-send.md) | 2026-09-17 | `whatsapp-agent send` reaches the phone: rate limiter, HTTP layer mapping every response onto auth / rejected / unavailable, markdown conversion and `(i/n)` chunking, the message store, and `--dry-run` |
| [GH-2-package-skeleton](completed/GH-2-package-skeleton.md) | 2026-09-17 | `pip install -e .` gives a working `whatsapp-agent`: version from `pyproject.toml`, five failure codes with unique exit statuses, token from env then `--token-file`, state under XDG and never the cwd, every subcommand present as a stub exiting 5. `tests/smoke.py` is the repo check and CI is now enforcing |

## Superseded
| Plan | Superseded by |
|---|---|
