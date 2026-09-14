---
type: Brainstorm
title: The relay's first release — extracting a personal poller into a configurable relay
description: What the first public release of the relay does, which parts of the personal poller carry over, what they must learn from hisab-whatsapp's transport, and the three questions only the author can answer.
tags: [brainstorm, extraction, transport, session-control, write-boundary]
timestamp: 2026-09-14T00:00:00Z
---

# The relay's first release — Brainstorm

## Problem

A developer wants to ask their coding agent something about a project while away from the machine: "what does the retry in the poller do", "add a note to the changelog", a voice note describing a bug, a screenshot of an error. Today the only thing that does this is a personal bash poller (about 440 lines plus a 74-line transcription helper) that has run on one server since 2026-09-06. It works, but it is shaped around one person's notes folder: its tool allow-list, its writable folders, its help text and one refused command are all hard-coded to that setup. Nobody else can run it without editing the script, and it predates what hisab-whatsapp later learned about the WhatsApp transport the hard way.

## Goal

The smallest release that counts: a developer points the relay at **one folder** with **one config file** naming that folder, the CLI agent, and the write paths; texts their WhatsApp agent; and gets the agent's full reply back — with voice notes transcribed, images and documents handed over by path, the session resettable and the model switchable from the phone, and nothing outside the declared write paths writable. Claude Code first; Codex behind the same seam second.

## What the personal poller already does (carry over, generalised)

Named by the function in today's script, with what the generic version needs:

| Behaviour | Today | Generic version |
|---|---|---|
| Reset (`is_reset_trigger`, `new_session_id`) | A fixed phrase list mints a new session id in the relay; no model call. In-agent `/clear` does not survive a non-interactive call | Same. The phrase list may become config; the rule that the relay owns it does not |
| Resume fallback | A failed `--resume` mints a new session and retries; a `.fresh` marker skips a doomed resume after a reset | Same, per adapter |
| Message store (`store_message`, `lookup_message`, `prune_store`) | JSONL keyed by WhatsApp id, in and out, pruned to 30 days; a quoted reply is resolved and put in front of the prompt, even after a reset | Same, plus dedup by id (see gaps). Format is open question 2 |
| Model switching (`model_id_for`, `current_model`, `is_model_command`) | `/model <name>` is stored by the relay and passed on every call; survives a reset on purpose | Same; the list of names belongs to the adapter (Claude and Codex name models differently) |
| Write boundary (`deny_settings`) | Per call, a deny rule for every top-level entry of the folder except the declared writable ones, built from the listing at call time so a new folder is denied. Passed as settings, never written to disk. Plus a hard-coded tool allow-list | Writable paths and allowed commands come from config. The deny list mechanism stays. Codex parity is an open question |
| Help (`is_skills_command`) | `/skills` and `/help` answered from the folder's skill files, no model call | Same idea, generic text; which skill directory depends on the adapter |
| Agent call (`run_claude`) | `claude -p` in the folder, `stream-json`, keeps **every** assistant text block (plain `-p` returns only the final message, which once dropped the answer and kept only a closing status line); stdin closed so the child cannot swallow the rest of the batch | Same, as the Claude Code adapter |
| Formatting and sending (`to_whatsapp`, `split_chunks`, `send_one`, `send_reply`) | Markdown → WhatsApp, split on paragraph boundaries under 3,500, numbered `(i/n)`, non-2xx treated as failure | Same |
| Media (`download_media`, `ext_for_mime`) | Two-hop download; images and voice notes only; mime matched on prefix (`audio/ogg; codecs=opus`) | Add documents (the README promises them); check the HTTP status of both hops |
| Voice (`transcribe_voice.py`) | One provider, a fixed prompt, exit code checked so a traceback is never handed to the agent as speech | Provider configurable, hisab's `hisab/transcribe.py` is the shape (an OpenAI-compatible endpoint or Gemini); language hint from config |

Personal-only behaviour that does **not** carry over: the fixed allow-list naming one vault's skills and scripts, the refused-command branch for one skill, the creator-id file written for scheduled jobs, and the interpreter-hunting for one machine's Python.

## Gaps between today's poller and the decisions already made

These are the reason this is a rewrite of the loop and not a copy:

1. **Offset is saved before the batch is processed.** A crash mid-batch loses messages. Decision: advance only after the batch.
2. **No dedup by message id.** A replayed update runs the agent twice. Decision: skip ids already in the store.
3. **HTTP status of the poll is never read.** A 429, 503, 409 or dead token looks like an empty batch and the loop spins. Decisions: back off on 429/503, log 409 as another poller, exit on a 401 or a 400 with `error.code` 100.
4. **No rate limiting.** The platform allows 15 polls, 12 sends, 12 status calls and 12 media calls per minute, each its own window. hisab's `RateLimiter` in `hisab/wa.py` paces proactively.
5. **No typing indicator.** An agent call can take a minute; the phone shows nothing.
6. **Failure text goes to the phone raw.** When the agent produces nothing, the tail of its stderr is sent as the reply. For a developer's own phone that is arguably useful, but it can carry paths and settings. Open question 6.
7. **Downloaded media is never cleaned up.**
8. **Documents and video are skipped** even though the README lists documents.

## Approaches considered

1. **Clean port in bash** — keep the script's shape, move the hard-coded values into a config file, fix gaps 1–8 in bash. Reuses today's script almost line for line and stays a single file on any box with `curl` and `jq`. Trade-off: the rate limiter, dedup and error classification are awkward in bash and hard to test without a network, transcription still needs Python anyway, and hisab's tested transport can only be re-derived, not carried.
2. **Python rewrite, standalone** — a small package: poll loop, store, transcription and the WhatsApp client shaped after hisab's `wa.py` / `store.py` / `transcribe.py` (copied through the privacy rule, not imported), plus an agent adapter seam with Claude Code as the first adapter. Reuses the invariants hisab already tests and a no-network check in the style of hisab's `tests/smoke.py`. Trade-off: a Python runtime on the server, and two copies of the transport that can drift from hisab.
3. **Python with a shared transport package** — extract hisab's WhatsApp client and store into a package both repos depend on. Reuses one implementation; fixes land once. Trade-off: couples two repos' release cycles for a transport that is ~250 lines, and hisab's store carries ledger-only fields (entry numbers, setup state, usage) that the relay does not want.

**Leaning toward:** 2, pending the author's answers to open questions 1 and 2 — every gap above is already solved and tested in hisab's Python, transcription is already Python, and a copy of a 250-line client is cheaper than a shared package until both products have stopped moving. If the answer to question 1 is bash, approach 1 still stands and the gaps list becomes its checklist.

## Surfaces touched

transport / session control / agent adapter / write boundary / transcription / store / config / deploy / docs

## Open questions

For the author — first, in this order:

- [ ] **1. Language of the rewrite.** Bash, as the poller is today, or Python, like hisab-whatsapp? (Approaches 1 vs 2/3.)
- [ ] **2. Is the message store format shared with hisab?** Same JSONL record (`id`, direction, timestamp, text) so tooling reads both, or the relay's own format with no promise between repos? And if Python: copy hisab's client, or share a package (approach 3)?
- [ ] **3. Multiple folders per WhatsApp agent in the first release.** One agent token ↔ one folder only; or several folders behind one agent, switched by a command (and then: does each folder keep its own session, model and write paths?); or several relay processes, which the platform forbids on one token (409), so that means one agent per folder.

Then, for the grill:

- [ ] **4. Codex and the write boundary.** Claude Code takes a per-call deny list and a tool allow-list. Codex's non-interactive mode has sandbox levels rather than per-path denies (to verify against `codex exec --help`). Is "read-only, or the whole folder writable" acceptable for the Codex adapter, or does Codex wait until per-path writes are possible?
- [ ] **5. Does a deny on edits cover every way to write?** Today's boundary is a deny on edit tools plus a narrow command allow-list. Confirm against Claude Code's permission docs that the deny covers every file-writing tool, and decide whether the config's "allowed commands" is part of the first release or the agent gets no shell at all.
- [ ] **6. What the phone sees when the agent fails.** Raw stderr tail (today), a fixed sentence with detail in the server log (hisab's rule), or a short, redacted summary.
- [ ] **7. Commands the relay answers itself.** Today: reset phrases, `/model`, `/skills`, `/help`. Is that the first-release set? Is the reset phrase list config?
- [ ] **8. Config and secrets.** One YAML file for folder, adapter, write paths, transcription; token from an environment variable or a token file path — which, or both?
- [ ] **9. Deploy shape.** A systemd unit, a container, or "run it however you like" plus an example. A container must mount the folder and carry the CLI agent and its login, which is not trivial for Claude Code.
- [ ] **10. Replies that are files.** hisab can send a document back; does the relay need to (an agent that produced a diff or a report), or is text enough for the first release?
- [ ] **11. The name.** Raised by the author on 2026-09-14: rename the repo to `whatsapp-agent-cli`. Argument against in brief: "-cli" usually names a command-line tool you type into, while this bridges WhatsApp to one; alternatives were `whatsapp-cli-bridge` and `whatsapp-to-cli-agent`. Cheap either way while the repo is private.

## Out of scope (YAGNI)

- Its own model loop or tools. The CLI agent is the brain.
- More than one person. The platform lets an agent message only its creator.
- Groups, webhooks, a web UI, a hosted multi-tenant mode.
- Scheduled or unprompted messages from the relay (today's creator-id file exists only for that).
- Anything ledger-shaped; that is hisab-whatsapp.
- Video and stickers.
