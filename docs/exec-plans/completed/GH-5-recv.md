---
type: ExecPlan
slug: GH-5-recv
issue: 5
status: completed
open_questions: none
---

# feat: recv — long-poll with cursor after batch, dedup and JSON output          ✅ COMPLETED — 2026-09-17

## Problem

[#5](https://github.com/mhmzdev/whatsapp-agent-cli/issues/5) is the other half of the transport. After it, a program can read what arrives on WhatsApp — `whatsapp-agent recv --follow --json` streams one JSON object per line, cursor, dedup, backoff and rate limits handled — which is the piece hisab-whatsapp and any relay actually need. It is also where every transport invariant lives, each one because the original bash poller gets it wrong (see the brainstorm's list of eight). And it records the creator, which retires `--to` being mandatory on `send`.

## Approach

`send` already landed the machinery: the rate limiter, the HTTP layer's three-outcome mapping, and the store. This ticket adds a `poll` to the client, a cursor to the store, and the `recv` command on top, plus one new failure code.

**Three decisions settled with the author before planning (2026-09-17):**

1. **A first run delivers only new messages.** The platform sends the backlog when asked for `offset=0` and only new traffic when the offset is omitted. Omitting it is the default, so a first `recv` in a script does not dump thirty days into whatever is reading stdout; `--replay` opts into the backlog deliberately.
2. **A 409 exits.** The platform allows one poller per token and answers 409 when a newer poll replaces an older one. Two pollers silently steal messages from each other, so this is a setup mistake, not a blip: `recv` exits with a new code, `another_poller` (9), naming the cause, in both one-shot and `--follow` mode.
3. **Never lose a message, even at the cost of repeating one.** The order per message is **print and flush → record as seen → (after the batch) advance the cursor**. A kill between printing and recording redelivers that message next run; a kill anywhere else is covered by dedup. The alternative — record then print — turns the same kill into a message nobody ever sees, which cannot be noticed downstream.

**The cursor.** `next_offset` from the response, written to `offset` in the state directory only after the whole batch has been printed and recorded. hisab's poller wrote it first (`poll_and_relay.sh`'s loop), which is how a crash mid-batch silently skips messages.

**Dedup.** `store.seen(id)` already exists. A message whose id is in the store is skipped before printing, so a redelivered batch — after a crash, or after `--replay` — produces nothing the caller has already had.

**Backoff.** The client retries a 429 once by itself. Beyond that, `platform_unavailable` in `--follow` sleeps and retries with exponential backoff (1s doubling to a 60s cap, reset on success); in one-shot mode it exits 7 and lets the caller decide. `AuthError` exits 4 immediately in both modes — the token will not heal.

**Output.** `--json` prints the platform's message object, one per line, flushed per line so a pipe sees each message as it arrives. Without it, one human line per message: local time, sender, type, and the text (or a `<image>`-style placeholder for media, whose bytes are #6's job). Media is never downloaded here; the message object carries the media id and #6 fetches it.

**`--transcribe`** stays in the parser and raises `not_implemented` naming #7, so the flag's shape is settled without pretending the feature exists.

## Success criteria

- [x] A message sent from the phone appears on stdout as one JSON object per line — `verify: python3 tests/smoke.py` (fake session) plus the manual phone step
- [x] The cursor advances only after the whole batch is printed and recorded; a crash mid-batch redelivers rather than skips — `verify: python3 tests/smoke.py`
- [x] A message id already in the store is never printed again — `verify: python3 tests/smoke.py`
- [x] A first run with no cursor asks for new traffic only; `--replay` asks for the backlog — `verify: python3 tests/smoke.py` asserts the request's params in both cases
- [x] 409 exits 9 naming the other poller, in one-shot and in `--follow` — `verify: python3 tests/smoke.py`
- [x] 401, or 400 with `error.code` 100, exits 4 immediately and polls no further — `verify: python3 tests/smoke.py`
- [x] In `--follow`, a 503 backs off exponentially and recovers; in one-shot it exits 7 — `verify: python3 tests/smoke.py` with an injected clock, asserting simulated sleep, never real
- [x] Polls are paced at 15/min and statuses at 12/min, each its own window — `verify: python3 tests/smoke.py`
- [x] `--typing` marks each delivered message read and shows the indicator; without it, nothing is sent to `/statuses` — `verify: python3 tests/smoke.py`
- [x] The creator is recorded from the first inbound message, after which `send` works without `--to` — `verify: python3 tests/smoke.py`
- [x] Ctrl-C during `--follow` exits 130 with the cursor where the last complete batch left it — `verify: python3 tests/smoke.py`
- [x] Repo check passes on 3.10 through 3.13 — `verify: python3 tests/smoke.py` locally, the CI matrix on the PR
- [?] Manual: a real message from the phone comes out of `recv` — `verify: manual 1. export WHATSAPP_AGENT_TOKEN=<demo agent token> 2. whatsapp-agent recv --follow --json 3. text the agent from the phone; the object appears within a second 4. Ctrl-C, then whatsapp-agent send "got it" with no --to, which now resolves the recorded creator`

## Phases

### Phase 1 — Poll, the cursor, and the 409 code
**Status:** Done
- Files: `whatsapp_agent/client.py`, `whatsapp_agent/errors.py`, `whatsapp_agent/store.py`, `tests/smoke.py`
- Change: `WhatsApp.poll(offset=None, limit=50, timeout=20, replay=False)` returning `(messages, next_offset)`; it flattens `entry[].changes[].value.messages[]`, treats 204 as an empty batch, and passes `offset` only when there is one or `replay` asked for `0`. `_checked` maps 409 to the new `another_poller` code (exit 9) before the generic 4xx rule. `WhatsApp.typing(message_id)` posts the read receipt plus indicator to `/statuses` and never raises — a failed receipt must not lose a message. `Store.offset()` / `set_offset()` read and write `offset` in the state directory.
- Test: a fake session proves the params for first run, resumed run and `--replay`; 204 and an empty `entry` both yield no messages; 409 raises `another_poller`; `typing` swallows a 500 but does post the documented body.

### Phase 2 — The command, one shot
**Status:** Done
- Files: `whatsapp_agent/cli.py`, `tests/smoke.py`
- Change: `recv` resolves token and state, polls once, and for each message: skip if `store.seen(id)`; print (JSON line or human line) and flush; record with `store.add(id, "in", text)`; record the creator from `from`; send typing when `--typing` is set. After the loop, `store.set_offset(next_offset)`. `--transcribe` raises `not_implemented` naming #7.
- Test: ordering proven by a store whose `add` raises after the first message — the first is printed and the cursor has not moved; dedup proven by polling the same batch twice; creator recorded and then used by a `send` with no `--to`.

### Phase 3 — Follow, backoff and interrupt
**Status:** Done
- Files: `whatsapp_agent/cli.py`, `tests/smoke.py`
- Change: `--follow` loops the Phase 2 body. `platform_unavailable` sleeps 1s, doubling to 60s, reset on any successful poll; `AuthError` and `another_poller` break out with their exit codes; `KeyboardInterrupt` returns 130 after the current batch finishes. Injected `sleep` so the check never waits.
- Test: a scripted session of 503, 503, then a batch asserts the simulated delays are 1s and 2s and that the batch is delivered; a 409 mid-follow exits 9; an interrupt between batches leaves the cursor at the last complete batch.

### Phase 4 — Checklist and manual pass
**Status:** Done
- Files: `docs/feat-checklist/GH-5-recv.md`, `docs/feat-checklist/INDEX.md`
- Change: record what was proven and write the manual phone steps, including the `send` with no `--to` that proves the creator was recorded.
- Test: the repo check, and the CI matrix on the PR.

## Risks

- **A fake session that lies about the envelope.** The platform nests messages under `entry[].changes[].value.messages[]`; the check builds fixtures in exactly that shape, and the manual step catches anything the shape misses.
- **Backoff tests that really sleep.** `sleep` is injected everywhere, as in #4.
- **A partial batch on a broken pipe.** If stdout closes mid-batch (`recv | head`), printing raises; the cursor must not advance. The command treats a write failure as the end of the run and exits without advancing.
- **Scope creep into #6 and #7.** No media bytes, no transcription: the message object carries a media id and that is all.

## Out of scope

- Downloading media — #6.
- Transcription — #7; the flag exists and refuses.
- Any interpretation of message content: quoted replies, commands, sessions. Layer B's business.

## What actually happened (2026-09-17)

Four phases as written. Notes:

1. **The follow-mode warning was reworded.** A code's message ends with advice ("retrying may help"), which read badly beside the actual retry: "the platform is unreachable right now; retrying may help; retrying in 1s". The warning now takes the first clause only — "warning: the platform is unreachable right now — retrying in 1s".
2. **The crash window is proven by a store that dies on purpose.** A `Store` subclass raises `KeyboardInterrupt` while recording the second message of a batch; the check then asserts the message was printed, was not recorded, the cursor did not move, and the next run redelivers exactly that one message.
3. **Verified live as well as with the fake.** With a dead token, both `recv` and `recv --follow` exited 4 in under a second against the real endpoint, which is the behaviour that matters: `--follow` must not spin on a token that will never work.

One papercut found and left alone, recorded as FINDING-05: global options go before the subcommand (`whatsapp-agent --state-dir X recv`), git-style. `recv --state-dir X` is a usage error. Fixing it in argparse means duplicating the globals onto every subparser, where subparser defaults then clobber values given on the main parser unless every one is `SUPPRESS`ed — more fragile than the papercut.
