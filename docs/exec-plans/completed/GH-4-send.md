---
type: ExecPlan
slug: GH-4-send
issue: 4
status: completed
open_questions: none
---

# feat: send — text to the phone with chunking and rate limits          ✅ COMPLETED — 2026-09-17

## Problem

[#4](https://github.com/mhmzdev/whatsapp-agent-cli/issues/4) is the first ticket that talks to WhatsApp. After it, `whatsapp-agent send "deploy finished"` puts a message on the creator's phone — the user story that makes this package useful to a script, a git hook or a coding agent, before anything can receive. It also lands the three pieces every later ticket reuses: the rate limiter, the HTTP layer with its error mapping, and the message store.

## Approach

Four new modules, each small enough to test without a network. hisab's `hisab/wa.py` is the prior art for all of them and its hard-won details carry over; what changes is where failures end up, since ours become exit codes rather than a chat reply.

- **`ratelimit.py`** — one rolling window per method, exactly as `hisab/wa.py:36`, with `now` and `sleep` injected so the check can prove pacing without waiting. `penalize` marks a window fully spent so a 429 backs off toward a real reset instead of a guessed delay (`hisab/wa.py:68`).
- **`client.py`** — a `WhatsApp` class taking an injected `session` (anything with `.request`), so the check drives it with a fake and the package still defaults to `requests`. `_request` rate-limits, retries once past a 429 (`hisab/wa.py:89`), then maps the response onto our codes: 401 or 400-with-`error.code`-100 → `AuthError`; any other 4xx → `platform_rejected` (permanent, retrying is pointless); 5xx, 429-after-retry, or a `requests` transport failure → `platform_unavailable` (retryable). This mapping is the piece #5 and #6 inherit unchanged.
- **`text.py`** — `to_whatsapp` (markdown → WhatsApp formatting) and `chunks` (split on paragraph boundaries under the cap), lifted from `hisab/wa.py:210` and `hisab/wa.py:223`, which already handle a single paragraph longer than the cap.
- **`store.py`** — append-only JSONL keyed by message id, records `{id, dir, ts, text}`, hisab's record shape per spec 001. `#4` only appends outgoing ids and reads them back; dedup on the way in is #5's.

`requests` is imported for the first time here, which retires FINDING-01 from #2's checklist.

**Recipient.** `--to` is required until something stores a creator id, because the platform's `to` must be the `from` of an inbound message. When #5 lands and records the creator, `--to` becomes optional; this ticket writes the lookup (`store.creator()`) but there is nothing to find yet, so a missing `--to` raises `no_recipient` explaining that recv has not run.

**Sleeping between parts.** hisab sleeps 1s between chunks (`hisab/wa.py:162`). Here the rate limiter already paces sends at 12/min, so the sleep is redundant and would double the wall clock of a long reply; it is dropped, and the check asserts a five-part send makes five calls with no extra delay beyond the limiter's.

## Success criteria

- [x] `whatsapp-agent send "text" --to <id>` posts to `/messages` and prints the returned message id — `verify: python3 tests/smoke.py` (fake session asserts the request shape) plus the manual phone step below
- [x] A body over the cap arrives as several parts, in order, each numbered `(i/n)` — `verify: python3 tests/smoke.py`
- [x] Markdown bold, headings and bullets convert to WhatsApp formatting — `verify: python3 tests/smoke.py`
- [x] A 401, or a 400 with `error.code` 100, exits 4 and is not retried — `verify: python3 tests/smoke.py`
- [x] Another 4xx exits 6; a 5xx or a transport failure exits 7; neither prints a traceback — `verify: python3 tests/smoke.py`
- [x] A 429 is retried once after the limiter backs off, and succeeds — `verify: python3 tests/smoke.py`
- [x] Sends are paced at 12/min without sleeping in real time during the check — `verify: python3 tests/smoke.py`
- [x] Outgoing ids land in the message store, one record per part — `verify: python3 tests/smoke.py`
- [x] No token ever appears in an error message, a detail line or the store — `verify: python3 tests/smoke.py`
- [x] Repo check passes on 3.10 through 3.13 — `verify: python3 tests/smoke.py` locally, the CI matrix on the PR
- [?] Manual: a real send reaches the phone — `verify: manual 1. export WHATSAPP_AGENT_TOKEN=<demo agent token> 2. whatsapp-agent send "hello from the CLI" --to user:<creator id> 3. the message arrives; the printed id matches the one WhatsApp shows`

## Phases

### Phase 1 — Rate limiter and text
**Status:** Done
- Files: `whatsapp_agent/ratelimit.py` (new), `whatsapp_agent/text.py` (new), `tests/smoke.py`
- Change: `RateLimiter` with injected `now`/`sleep`, mirroring `hisab/wa.py:36-72`; `to_whatsapp` and `chunks` from `hisab/wa.py:210-239`. Pure functions, no HTTP.
- Test: 30 instant calls against a 12/min limit pace into a second window with a fake clock; `penalize` pushes the next acquire toward a reset; chunking splits on blank lines, hard-cuts an over-long paragraph, and never emits an empty part; `to_whatsapp` converts `**bold**`, `# heading` and `- bullet`.

### Phase 2 — The client and its error mapping
**Status:** Done
- Files: `whatsapp_agent/client.py` (new), `whatsapp_agent/errors.py` (three codes), `tests/smoke.py`
- Change: `WhatsApp(token, session=None, ...)`; `_request` with the 429 retry; `send(to, text)` returning message ids; `platform_rejected` (6), `platform_unavailable` (7) and `no_recipient` (8) added to `CODES`. Every raise carries the status and a truncated body in `detail`, never in `message`, and never the Authorization header.
- Test: a fake session returning scripted responses covers 2xx, 401, 400/100, 400/other, 429-then-2xx, 500 and a raised transport error; the check asserts the posted JSON is exactly the platform's documented shape.

### Phase 3 — The store
**Status:** Done
- Files: `whatsapp_agent/store.py` (new), `tests/smoke.py`
- Change: `Store(state_dir)` with `add(id, direction, text)`, `lookup(id)`, `creator()`/`set_creator()`, and a 30-day prune on open. JSONL, one object per line, hisab's field names.
- Test: records round-trip; a second `Store` on the same directory sees them; prune drops an old record and keeps a fresh one; the file lands inside the state dir and nowhere else.

### Phase 4 — Wire up the command
**Status:** Done
- Files: `whatsapp_agent/cli.py`, `tests/smoke.py`, `docs/feat-checklist/GH-4-send.md`
- Change: `send` resolves the token, builds the client, sends, records each part in the store and prints one id per line. A missing `--to` with no stored creator raises `no_recipient`. `--dry-run` prints the parts that would be sent and makes no call, so the manual step can be rehearsed without spending a message.
- Test: end-to-end through `cli.main` with a fake session and a temp state dir; the stub assertion for `send` is replaced by a real one, and every other stub still exits 5.

## Risks

- **A fake session that lies.** The check asserts the exact request shape the manual gives (`messaging_product`, `to`, `type`, `text.body`), so a passing fake and a failing phone can only diverge on the platform's own behaviour, which the manual step catches.
- **Rate-limiter tests that actually sleep.** `now` and `sleep` are injected; the check asserts total simulated time, never real time.
- **Scope creep into #5.** No polling, no cursor, no dedup here. `store.creator()` exists but nothing populates it yet, by design.

## Out of scope

- `recv`, the cursor, dedup — #5.
- Media and documents — #6.
- Typing indicators and read receipts — they ride with #5.
- Retry policy beyond the single 429 retry: a caller that wants more loops on exit 7.

## What actually happened (2026-09-17)

Four phases as written. Three notes:

1. **`send` returns `Sent(id, text)` per part, not a bare id.** The first cut returned ids and left the CLI re-running the split to know what text each id carried — two code paths that could drift. The namedtuple makes the client the only place that decides what goes on the wire, and `parts_for` exposes that split for `--dry-run`.
2. **`--dry-run` was added.** It prints exactly what would be sent and makes no call and needs no token, so the manual phone step can be rehearsed without spending a message against the 12/min budget.
3. **The error mapping was verified against the live API, not only the fake.** A deliberately invalid token produced `HTTP 400 error.code 100` from the real endpoint and came out as exit 4 with the fixed message, which is the same path the fake session asserts.

The `requests` dependency is now imported (lazily, inside `WhatsApp.__init__`), retiring FINDING-01 from #2's checklist: `import whatsapp_agent` still does not pull it in.
