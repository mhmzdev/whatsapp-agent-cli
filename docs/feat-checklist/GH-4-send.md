---
type: FeatChecklist
slug: GH-4-send
issue: 4
timestamp: 2026-09-17T00:00:00Z
---

# GH-4-send — acceptance checklist   (10 proven · 1 manual · 0 failing)

Criteria from [#4](https://github.com/mhmzdev/whatsapp-agent-cli/issues/4) and its plan. Every `[x]` was run this session; the client checks drive a fake session, and one deliberate live call confirmed the fake tells the truth.

- [x] `send --to <id>` posts the platform's documented body and prints the returned id — check's "client" and "send end to end" sections assert `{messaging_product, to, type, text.body}` exactly
- [x] A body over the cap arrives as several parts, each numbered `(i/n)` — check's "text" and "client" sections; an 8,000-character body becomes three calls, each part numbered
- [x] Markdown bold, headings and bullets convert — check's "text" section, and visible in the installed command's `--dry-run`
- [x] A 401, or a 400 with `error.code` 100, exits 4 and is not retried — check's "client" section, **and confirmed against the live API** with a deliberately invalid token: `HTTP 400 error.code 100` came back as exit 4 with the fixed message
- [x] Another 4xx exits 6; 5xx, a transport failure and a persistent 429 exit 7 — eight scripted failure modes in the check
- [x] A 429 is retried once after the limiter backs off, and succeeds — check asserts two calls and a success
- [x] Sends are paced at 12/min with no real sleeping — 30 acquires span 120s of simulated time on an injected clock; `penalize` backs off 60s
- [x] Outgoing ids land in the store, one record per part — check's "send end to end" section reads the text back by id from a second `Store`
- [x] No token reaches an error message, a detail line or the store — asserted for every failure mode, and for the no-token path
- [x] `--to` falls back to the creator the store records, and raises `no_recipient` (exit 8) when there is none — check's "send end to end" section
- [?] A real send reaches the phone — needs the demo agent's token: `export WHATSAPP_AGENT_TOKEN=…` then `whatsapp-agent send "hello from the CLI" --to user:<creator id>`. Rehearse it first with `--dry-run`, which costs nothing.

## Conventions

- **Layer purity** — nothing here knows about agents, folders, sessions or models. `store.creator()` exists but only #5 populates it.
- **Failures** — three new codes (6 rejected, 7 unavailable, 8 no recipient), all with unique exit statuses. The 6/7 split is the one a caller acts on: 7 is worth looping on, 6 never is.
- **Dependencies** — still exactly one runtime dependency, imported lazily inside `WhatsApp.__init__`, so `import whatsapp_agent` does not pull in `requests`.
- **No network in the check** — every client test drives an injected fake session; the only live call was run by hand, outside the check.

## Findings

**FINDING-01 (from #2) — retired.** `requests` is now imported and used.

**FINDING-03 · Minor · `whatsapp_agent/cli.py`** — the `detail:` line prints the platform's response body, which is right for an operator debugging their own agent but means an HTTP body does reach stderr. The fixed `message` never carries it, and the token never appears in either. Worth revisiting only if the CLI ever prints into something shared.

**FINDING-04 · FIXED in #6's branch** — a send that splits into five parts and fails on part three leaves the first two delivered. The API has no transaction, so that cannot be prevented; what was wrong was that `send` returned only at the end, so the failure threw away the knowledge of which parts had arrived. `send_iter` now yields each part as it leaves, and the CLI prints and records it at once. The ids of delivered parts survive the failure.
