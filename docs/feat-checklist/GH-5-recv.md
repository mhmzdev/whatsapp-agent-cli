---
type: FeatChecklist
slug: GH-5-recv
issue: 5
timestamp: 2026-09-17T00:00:00Z
---

# GH-5-recv — acceptance checklist   (11 proven · 1 manual · 0 failing)

Criteria from [#5](https://github.com/mhmzdev/whatsapp-agent-cli/issues/5) and its plan. Fake sessions drive the transport; two live calls against the real endpoint confirm the fake tells the truth about auth.

- [x] A message appears on stdout as one JSON object per line, and as one readable line without `--json` — check's "recv" section
- [x] The cursor advances only after the whole batch is printed and recorded — check's "crash window" section: a store that dies mid-batch leaves the cursor untouched
- [x] A kill mid-batch redelivers rather than skips — the same section asserts the killed message is printed, unrecorded, and delivered again on the next run
- [x] A message id already in the store is never printed again — a redelivered batch produces no output at all
- [x] A first run asks for new traffic only; `--replay` sends `offset=0`; a resumed run passes its cursor back unchanged — asserted on the request params
- [x] A 409 exits 9 naming the other poller — proven in one-shot; `--follow` re-raises it rather than retrying
- [x] 401, or 400 with `error.code` 100, exits 4 immediately — proven with the fake **and live**: a dead token exits 4 in under a second, in both one-shot and `--follow`
- [x] In `--follow`, unavailability backs off 1s then 2s and recovers; in one-shot it exits 7 — asserted against an injected sleep, never real time
- [x] Polls pace at 15/min and statuses at 12/min, each its own window — inherited from #4's limiter, exercised by the poll tests
- [x] `--typing` posts a read receipt and indicator per delivered message; without it nothing reaches `/statuses` — asserted both ways, and the posted body matches the manual
- [x] The creator is recorded from an inbound message, after which `send` works with no `--to` — the check sends immediately after receiving, with no recipient given
- [x] Ctrl-C during `--follow` exits 130 with the cursor at the last complete batch
- [?] A real message from the phone comes out of `recv` — needs the demo agent's token: `export WHATSAPP_AGENT_TOKEN=…`, then `whatsapp-agent recv --follow --json`, text the agent, watch the object appear, Ctrl-C, then `whatsapp-agent send "got it"` with no `--to`

## Conventions

- **Layer purity** — `recv` interprets nothing. A quoted reply, a command, a session: all layer B. Media is emitted as an id; the bytes are #6 and transcription is #7, which `--transcribe` says out loud by refusing with `not_implemented`.
- **Failures** — one new code, `another_poller` (9). Nine codes, all with unique exit statuses, none leaking a body into its message.
- **No network in the check** — every transport test drives an injected fake session and an injected sleep; the two live calls were run by hand.

## Findings

**FINDING-05 · Minor · `whatsapp_agent/cli.py`** — global options must precede the subcommand: `whatsapp-agent --state-dir X recv` works, `whatsapp-agent recv --state-dir X` is a usage error. This is how git and docker behave, so it is defensible, but it will trip people. The argparse fix (duplicating globals onto every subparser) introduces a worse trap, where a subparser's default silently clobbers a value given on the main parser. Worth a README line rather than code.

**FINDING-06 · Minor · `whatsapp_agent/state.py`** — the state directory is created even when the command then fails, so a `recv` with a bad token leaves an empty directory behind. Harmless, and creating it lazily would mean threading the decision through every caller.

**FINDING-04 (from #4) — still open.** A multi-part send that fails halfway leaves the earlier parts delivered. Unchanged by this ticket.
