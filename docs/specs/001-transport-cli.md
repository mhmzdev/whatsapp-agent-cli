---
type: Spec
slug: transport-cli
status: draft
last_verified: 2026-09-17
---

# 001 — whatsapp-agent-cli, the transport layer — Spec

Brainstorm: [transport-cli-first](../brainstorm/transport-cli-first.md). This spec covers **layer A only** — the transport. The relay (layer B) is a later release and is out of scope here.

## Problem

The WhatsApp Agent Platform has no webhooks and no client library. Every program that wants to use it writes the same few hundred lines: a long-poll with a stored cursor, per-method rate limits, a 4,096-character send cap, a two-hop media download, and a set of error codes where one means "back off" and another means "this token is dead, stop". Two programs have already written them — a personal bash poller and [`hisab-whatsapp`](https://github.com/mhmzdev/hisab-whatsapp) — and the bash one gets four of those wrong in ways that silently lose messages.

## Solution

A pip-installable Python package, `whatsapp-agent-cli`, that owns the transport and nothing else. It is a library first (`import whatsapp_agent`) with a command-line tool on top (`whatsapp-agent`), so a Python program imports it and a shell script, cron job or coding agent calls the command.

It knows about tokens, the cursor, rate limits, media and transcription. It knows nothing about coding agents, folders, permissions, sessions or models — those belong to layer B, which will be built on this.

## User stories

1. As a **developer**, I run `whatsapp-agent send "deploy finished"` from a script or a git hook and get the message on my phone.
2. As a **coding agent with shell access**, I call the same command when a long task finishes, so the person who started it hears about it without watching a terminal.
3. As a **program that needs incoming messages**, I run `whatsapp-agent recv --follow --json` and read one JSON object per message from stdout, with the cursor, dedup, backoff and rate limits handled for me.
4. As **hisab-whatsapp**, I add this package as a dependency, delete my own WhatsApp client and transcription module, and keep everything else.
5. As **someone receiving a voice note**, I get its text, because `recv --transcribe` (or `whatsapp-agent transcribe <file>`) turns the audio into words before I ever see it.

## Decisions

**Package and naming.** Distribution `whatsapp-agent-cli`, command `whatsapp-agent`, importable module `whatsapp_agent`. Library first; the CLI is a thin front door over the same functions.

**Subcommands (v1).**
- `send <text>` — split under the cap on paragraph boundaries, numbered `(i/n)` when split, markdown converted to WhatsApp formatting. Prints the resulting message ids.
- `recv` — new messages since the stored cursor, one JSON object per line with `--json`, human-readable otherwise. `--follow` holds the long-poll open and streams. `--transcribe` replaces a voice note's payload with its text.
- `media get <id>` / `media put <path>` — download to a directory, or upload and return the media id.
- `transcribe <file>` — audio file in, text out; the same code path `recv --transcribe` uses.
- `typing <message-id>` and read receipts — sent through the statuses endpoint; exposed as flags rather than a top-level command unless the grill says otherwise.

**State.** No concept of a project folder. The token comes from `WHATSAPP_AGENT_TOKEN` or `--token-file`; the cursor, message store and downloaded media live in an XDG state directory (`~/.local/state/whatsapp-agent/<profile>/`, `--state-dir` to override, `default` when no profile is named). Nothing is ever written into a caller's working directory.

**The message store** stays, keyed by WhatsApp message id, holding `id`, direction, timestamp and text — hisab's record shape, so both read the same file. It exists so `recv` can skip ids it has already delivered and so a caller can look up a quoted message's text. Resolving that text *into a prompt* is layer B's job, not ours. Pruned to 30 days.

**Transport invariants** (each one exists because the bash poller gets it wrong):
- The cursor advances only after a batch is fully delivered.
- A message id already in the store is never delivered twice.
- Every response's HTTP status is read. 429 and 503 back off exponentially; 409 means another poller took the cursor and is reported as such; a 401, or a 400 with `error.code` 100, means the token is dead — exit non-zero, never retry.
- A per-method rate limiter paces requests proactively: 15/min updates, 12/min messages, 12/min statuses, 12/min media, each its own rolling window.
- Downloaded media is deleted once the caller is done with it, or swept on a later run.

**Failures** are exit codes plus a message on stderr, never a stack trace, and never the raw HTTP body. The library raises typed exceptions; the CLI turns them into codes. Whether text ever goes back to a phone is the caller's decision, not ours.

**Transcription** is an optional extra (`pip install whatsapp-agent-cli[transcribe]`) with a configurable provider — an OpenAI-compatible endpoint or Gemini, mirroring `hisab/transcribe.py`. Absent the extra, `recv --transcribe` fails with a clear code rather than a traceback.

**Not in A:** folders, write paths, sessions, models, permissions, spawning an agent. `whatsapp-agent relay` arrives in the next release and uses this package like any other caller.

## Testing decisions

A no-network check is the seam, in the style of hisab's `tests/smoke.py`: a fake transport exercises chunking, dedup, cursor-after-batch, rate-limit pacing, error classification and the store, with no token and no HTTP. It becomes the repo's `check:` in `AGENTS.md`, which today reads `none yet`.

Above that, one manual pass against a real demo WhatsApp agent — send, receive, a voice note, a photo, a document — recorded in the feature's checklist. Publishing to PyPI and installing the published wheel in a clean environment is itself a criterion.

## Out of scope

- Layer B in any form.
- Anything hisab-side; its migration is a future issue in its own repo, after this is published.
- Groups, multiple recipients, webhooks, video, stickers.
- A hosted or multi-tenant mode.

## Further notes

Open questions carried from the brainstorm, for the grill or for the epic's first slice: whether `recv` on a 409 fails loudly or waits and retries; whether typing and read receipts are flags or their own command; the PyPI version scheme and what "published" means for the ship gate.
