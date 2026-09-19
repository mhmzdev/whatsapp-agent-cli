---
type: Brainstorm
title: whatsapp-agent-cli — the transport layer first, the relay second
description: The product is a pip-installable WhatsApp Agent Platform client that knows nothing about coding agents (layer A), with the phone-to-agent relay as a later command built on it (layer B). Decisions from the 2026-09-17 grill, and what the personal poller contributes to each layer.
tags: [brainstorm, extraction, transport, cli, packaging]
timestamp: 2026-09-17T00:00:00Z
---

# whatsapp-agent-cli — Brainstorm

> Rewritten 2026-09-17 after grilling, and renamed from `relay-first-release.md`. The first version of this document assumed the relay itself was the product; it is not. The relay is one user of the product. History in git.

## Problem

Two programs need the same WhatsApp Agent Platform transport, and both carry their own copy. A personal bash poller (about 440 lines, running on one server since 2026-09-06) relays messages to a coding agent over a folder. [`hisab-whatsapp`](https://github.com/mhmzdev/hisab-whatsapp) polls the same platform for a ledger. The bash one predates everything hisab later learned the hard way — it saves the poll cursor before the batch is processed, never reads the poll's HTTP status, has no dedup and no rate limiting. Any third thing built on this platform would start from zero again.

## Goal

One pip-installable package that owns the transport and nothing else: `pip install whatsapp-agent-cli`, then `whatsapp-agent send`, `recv`, `media`, `transcribe` from a shell, or `import whatsapp_agent` from Python. It never learns what a coding agent is.

## The two layers

**A — transport (this release).** Tokens, the poll cursor, the message store, rate limits, the 4,096-character cap, media, transcription. No folder, no agent, no permissions, no model. Two confirmed users: hisab-whatsapp (which drops its own copy once A is published) and the relay below.

**B — the relay (later).** Reads a message, runs a coding agent over a folder, sends the answer back. Claude Code first. Owns everything agent-shaped: the write boundary, session control, model switching, the help command. Ships as a command inside the same package, once A is real.

**The rule that keeps them apart:** B may use A; A may never know B exists. State that belongs to B (session ids, write paths, which agent) lives in B's own files, never in A's config or message store. If A's store starts carrying agent state, the layering has broken.

## Decisions (locked in the grill, 2026-09-17)

1. **Python**, not bash. Everything the bash script is missing already exists as tested Python in hisab.
2. **Package `whatsapp-agent-cli`, command `whatsapp-agent`, module `whatsapp_agent`.** Library first, CLI on top — hisab is Python and will import it, not shell out to it.
3. **A ships and is published before any B code is written.** Hisab moving onto A in production is the only honest proof that A is right. The ship order is a real gate, not a preference.
4. **Hisab's repo is not touched in this release.** Its migration is a future issue there, after A is published.
5. **State lives outside any project folder** — an XDG state directory, token from the environment or a token file. A has no concept of a project folder; that idea belongs to B.
6. **Message store keeps hisab's record shape** (`id`, direction, timestamp, text) so both read the same file. A copy for now; the shared implementation arrives when hisab migrates, which is what ends the drift.
7. **Transcription belongs to A**, behind an optional extra (`pip install whatsapp-agent-cli[transcribe]`): bytes in, text out, no agent involved, and hisab needs it too.
8. **One token, one poller.** The platform answers 409 when a second poll replaces the first, so any long-poll command must assume it is the only one.
9. **The name.** `whatsapp-agent-cli`, renamed from `whatsapp-agent-relay` on 2026-09-17: the product is the command-line tool; the relay is one thing it can do.

## What the personal poller contributes

To **A**, generalised — the two-hop media download with mime prefix matching (`audio/ogg; codecs=opus`), paragraph-boundary chunking with `(i/n)` numbering, markdown → WhatsApp formatting, the message store keyed by WhatsApp id with 30-day pruning, and a transcription step whose exit code is checked so a traceback is never mistaken for speech.

To **B**, when it comes — reset handling and session ids minted by the relay (an in-agent `/clear` does not survive a non-interactive call), the resume-then-fallback path, relay-owned model switching, the deny list built from the folder listing at call time so a new folder is denied by default, the help command answered without a model call, and keeping every assistant text block rather than only the final message.

Not carried over at all: the hard-coded allow-list naming one setup's skills and scripts, the refused-command branch for one skill, the creator-id file written for scheduled jobs, and the interpreter hunt for one machine.

## The eight gaps A must not inherit

1. Cursor saved **before** the batch is processed — a crash mid-batch loses messages. Advance only after.
2. **No dedup.** A replayed update is delivered twice. Skip ids already in the store.
3. **Poll HTTP status never read** — 429, 503, 409 and a dead token all look like an empty batch. Back off on 429/503, log 409 as another poller, exit on 401 or a 400 with `error.code` 100.
4. **No rate limiting.** 15 polls, 12 sends, 12 statuses, 12 media calls per minute, each its own window.
5. **No typing indicator**, so a slow caller shows nothing on the phone.
6. **Raw stderr sent to the phone** on failure — it can carry paths and settings.
7. **Downloaded media never cleaned up.**
8. **Documents unsupported** though they are part of the promise.

## Surfaces touched

transport / media / transcription / store / config and state / packaging and release / docs

## Open questions

Settled enough for a spec; these are the details the spec pins down and the grill can still move:

- [ ] Subcommand surface for A: `send`, `recv` (with `--follow` for long-poll and `--json` for machine output), `media get|put`, `transcribe`. Anything else in v1?
- [ ] What `recv` does when it detects another poller (409): fail loudly, or wait and retry?
- [ ] Token source: environment variable, `--token-file`, or both.
- [ ] Does A keep the message store at all, or only the cursor? (Dedup needs it; resolving a quoted reply's text is B's job.)
- [ ] Release mechanics: PyPI name, versioning, and what "published" means for the gate in decision 3.

## Out of scope (YAGNI)

- Anything agent-shaped in A: folders, write paths, sessions, models, permissions. That is B.
- Its own model loop or tools.
- More than one person. The platform lets an agent message only its creator.
- Groups, webhooks, a web UI, a hosted multi-tenant mode.
- Video and stickers.
- Changes to hisab-whatsapp in this release.
