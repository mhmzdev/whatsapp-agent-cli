---
type: ExecPlan
slug: GH-32-doctor
issue: 32
status: completed
open_questions: none
---

# feat: `wa-agent doctor` diagnoses a setup without disturbing it          ✅ COMPLETED — 2026-09-19 (Phases 1 and 5 post-merge)

## Problem

[#32](https://github.com/mhmzdev/whatsapp-agent-cli/issues/32). The first ten minutes of using the tool decide whether it is kept, and most failures in them are setup: a token pasted across two lines, the wrong Python, a key in the wrong variable, a state directory that cannot be written. Each surfaces today as its own exit code the first time the relevant command runs. One command should check all of it and say, a line per check, what is wrong and what to do.

The constraint that makes it more than a checklist: **checking the token must not poll.** `GET /updates` from `doctor` would take the long-poll from a running `recv` (or a relay) and hand it a 409, so the diagnostic would break the thing it diagnoses. The token needs an authenticated request with no side effects.

## Approach

**One new module, `wa_agent/doctor.py`,** holding the checks as plain functions that each return a `Check(name, status, message, fix)`. `status` is one of `ok`, `fail`, `optional`. A `run_checks(...)` function takes everything by injection (`env`, `session`, `python_version`, the state directory arguments) so the smoke check drives it with the same fake session the rest of the suite uses. `cli.py` gains a thin `doctor` subcommand that prints the checks and, when any is `fail`, raises one registered failure so the exit status comes out of the existing `main` path (`_fail`) like every other command.

**Six lines, in this order,** because each later line can depend on an earlier one:

| Check | Passes when | Fix printed on failure |
|---|---|---|
| `python` | the running interpreter is at least `MIN_PYTHON` (3.10) | install 3.10 or newer |
| `token` | present (env, then `--token-file`, same precedence as `resolve_token`), free of internal whitespace, and accepted by the platform | export `WHATSAPP_AGENT_TOKEN` / pass `--token-file` before the subcommand / get a fresh token / check the connection, depending on which failed |
| `gemini key` | **optional**, read from `GEMINI_API_KEY` (`transcribe.KEY_ENVS`). Absent → `optional`. Present and rejected → `fail`. Present but unverifiable (network, 5xx, 429) → `optional` | rejected: put a valid key in `GEMINI_API_KEY`, or unset it; absent: nothing to fix, only needed for `--provider gemini` |
| `openrouter key` | **optional**, read from `OPENROUTER_API_KEY`, same three outcomes as the line above | rejected: put a valid key in `OPENROUTER_API_KEY`, or unset it; absent: only needed for `--provider openrouter` |
| `state dir` | resolves without creating it, and is writable, or does not exist yet and its nearest existing parent is writable | fix the permissions, or point `--state-dir` elsewhere |
| `creator` | one has been recorded (`Store.creator()`) | send your agent a message while `wa-agent recv` runs; `send` needs `--to` until then |

**Never disturbs.** `doctor` creates nothing: it resolves the state directory with `create=False`, tests writability with `os.access` and never writes a probe file, and reads the creator without `Store` writing. It never touches the cursor or the message log. The smoke check proves it by listing a temp directory before and after.

**The token probe.** A new additive method `WhatsApp.probe_token()` in `wa_agent/client.py` issues `GET /media/<PROBE_MEDIA_ID>` through the client's own rate limiter and session, and classifies the answer itself instead of going through `_checked`, because `_checked` collapses every 4xx into one code and the probe has to tell "404, the token is good" from "403, something else". The mapping lives in one small table so the live verification (Phase 1) changes constants, not logic:

| Answer | Meaning | Result |
|---|---|---|
| 404 (or any 2xx) | the token is accepted; the id simply does not exist | returns |
| 401, or 400 with `error.code` 100 | the token is dead | raises `AuthError` |
| transport error, 408/425/429/5xx | could not verify | raises `platform_unavailable` |
| anything else (403, other 400s) | the platform answered something the mapping does not know | raises `platform_rejected`; `doctor` prints "answered something unexpected", never "token good" |

**That mapping is a hypothesis, not a fact.** The issue says it "has to be confirmed against the live platform before it is relied on", and there is a specific way it can be wrong: `400` with `error.code` 100 is Graph-style "invalid parameter", which is also what a *malformed* media id can produce with a *good* token. The client's existing rule reads that pair as a dead token, so a badly chosen probe id would make `doctor` call every good token dead. Phase 1 therefore has the owner run the probe live, with a good and a deliberately bad token, against candidate ids, and the constants are set from what comes back.

**The two key probes** have the same shape and the same caveat, and live in `doctor.py` (not `transcribe.py`, so the shared transcription module stays untouched). Each provider's default variable comes from `transcribe.KEY_ENVS`; there is **no `--key-env`** (ambiguous with two keys, and YAGNI for a diagnostic). Each probe is one authenticated `GET` through the same injected session, metadata only: no generation, no audio, no cost.

| Provider | Probe | Rejected (`fail`) | Accepted |
|---|---|---|---|
| gemini | `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1`, header `x-goog-api-key` | 400, 401, 403 | 2xx |
| openrouter | `GET https://openrouter.ai/api/v1/key`, header `Authorization: Bearer <key>` | 401, 403 | 2xx |

Everything else — a transport error, 408/425/429/5xx, or a status the table does not know (a 404 from a moved endpoint) — is `optional` "could not verify", never `fail` and never "accepted": an optional feature's network blip or an endpoint that moved must not fail a script.

**The OpenRouter path is confirmed from the docs, the status mapping is not.** OpenRouter's rate-limit and credits page says "to check the rate limit or credits left on an API key, make a GET request to `https://openrouter.ai/api/v1/key`" (read from the docs; no call was made to the API), which is what makes it free and side-effect-free. The same page does not say what an invalid key answers, so 401/403 as "rejected" is an assumption, in the same position as the Gemini one and the WhatsApp one. All three are labelled unconfirmed in a code comment and the PR body and are checked in Phase 1 after merge.

**Exit status.** One new registered code, `doctor_failed`, exit 15, not retryable. The report is the diagnosis; a script branches on `0` versus `15`. It does not reuse `auth` (4) because a failing state directory is not an auth failure. Adding it is one `CODES` row plus one row in `docs/errors.md`, which the existing "documented codes" section already enforces in both directions.

**Invariants kept.** Read-only by default is untouched (doctor grants nothing). The token and both provider keys are never printed: every line is fixed text (a line names the variable, never its value), no exception text is ever echoed, and the smoke check asserts all three secret strings are absent from stdout and stderr, including with `WHATSAPP_AGENT_DEBUG=1`. Secrets come only from the environment or `--token-file`. Privacy: fixtures use made-up tokens and a fake state directory. Dead-token semantics stay aligned with `errors.py`: 401, or 400 with `error.code` 100, is dead.

**Decisions, stated so the lead can veto them.**
1. A recorded creator is a **check that can fail**, not an advisory. The issue lists it beside the others with a fix; the only optional items are the provider keys.
2. A provider key that is **present but rejected is `fail`**; absent is `optional`; present but unverifiable is `optional`. Both providers, independently: a rejected OpenRouter key fails the run even when Gemini is fine.
3. A token that cannot be verified because the network is down is `fail` ("could not reach the platform"), because the point of the line is a verified token.
4. No `--json`, no auto-fix, no colour: out of scope.
5. **No options of its own.** `--key-env` is dropped; `doctor` checks each provider's default variable. Someone who keeps a key under another name sees it reported absent (`optional`), which is truthful for what `recv`/`transcribe` read by default.

## Success criteria

- [x] `wa-agent doctor` prints one line per check with `ok` / `FAIL` / `optional` and, on a failure, a `fix:` line — `verify: python3 tests/smoke.py` (asserts six lines, each status, and that every `FAIL` is followed by a fix)
- [x] It exits non-zero (`doctor_failed`, 15) when any check fails and 0 when none does — `verify: python3 tests/smoke.py`
- [x] Checking the token makes no request to `/updates`, proven with a fake session: in every scenario the recorded calls contain no `/updates`, and the token check makes exactly one call, a `GET` on `/media/…` — `verify: python3 tests/smoke.py`
- [x] Each provider key is its own line and its own outcome: absent → `optional`; present and rejected → `fail`; present but unverifiable (transport error, 429, 5xx) → `optional`. The run exits 0 with both keys absent if everything else passes — `verify: python3 tests/smoke.py`
- [x] `doctor` has no `--key-env`: `wa-agent doctor --key-env X` exits 2 — `verify: python3 tests/smoke.py`
- [x] The OpenRouter probe is a `GET` on `https://openrouter.ai/api/v1/key` and the Gemini probe a `GET` on the models listing; neither is a `POST`, neither touches a transcription or generation endpoint, and neither sends a body — `verify: python3 tests/smoke.py`
- [x] A dead token (401, and 400 with `error.code` 100) fails the token line with a "get a fresh token" fix; an unreachable platform (transport error, 429, 503) fails it with "could not reach"; neither claims the token is good — `verify: python3 tests/smoke.py`
- [x] `doctor` writes nothing: a temp state directory (existing and absent cases) is byte-identical before and after — `verify: python3 tests/smoke.py`
- [x] None of the token, the Gemini key and the OpenRouter key appears in stdout or stderr, with and without `WHATSAPP_AGENT_DEBUG=1` — `verify: python3 tests/smoke.py`
- [x] `MIN_PYTHON` agrees with `requires-python` in `pyproject.toml`, and an older interpreter fails the python line — `verify: python3 tests/smoke.py`
- [x] `doctor_failed` is documented: `errors` output, `docs/errors.md` and `CODES` agree — `verify: python3 tests/smoke.py`
- [x] The README documents `doctor` and the check still finds every documented command in `--help` — `verify: python3 tests/smoke.py`
- [ ] **The status mapping is confirmed live, after merge**, and the results are recorded in this plan under "Probe results": a good token gets the answer the table assumes for the chosen id, a bad token gets 401 or 400/100, and the Gemini probe and the OpenRouter `/api/v1/key` probe each distinguish a good key from a bad one — `verify: manual` (Phase 1; the owner and the lead run it after the PR merges; **this box stays unticked until then**, and no live call is made from this lane)
- [ ] `wa-agent doctor` run for real on the demo agent, while a `recv --follow` is polling in another terminal, passes and does not cost the poller a 409 — `verify: manual` (Phase 5; post-merge, owner and lead; **unticked** until then)
- [x] `send`, `recv`, `media`, `transcribe` (both providers) and `recv --json` behave as before, and `poll`, `send_iter`, `download`, `Store` and `transcribe.transcribe` return what they returned — `verify: python3 tests/smoke.py` (the existing sections, unmodified apart from adding `doctor` to the `--help` list)
- [x] Repo check passes — `verify: python3 tests/smoke.py`

## Phases

### Phase 1 — Live verification of the probes
**Status:** Not started — **post-merge, owner and lead only.** The owner's rule is no live runs from this lane (the demo token is shared with Hisab, and a second poller steals its messages), so nothing here is executed before the PR merges. The steps are written down so they can be run as-is afterwards. Phases 2–4 do not wait on it; the mapping constants ship as an assumption, labelled as one in the code comment and the PR body.
- Files: this plan (the "Probe results" section below), nothing else. No repo code runs live.
- Change: the owner or lead, after merge, with the demo agent's token in `$WHATSAPP_AGENT_TOKEN`, a Gemini key in `$GEMINI_API_KEY` and an OpenRouter key in `$OPENROUTER_API_KEY`, runs the probes below and pastes the status line and `error.code` (never a token or key, never a body beyond the error object) into "Probe results". Every request is a `GET`, none is `/updates`.
  1. **Good token, candidate ids.** `curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $WHATSAPP_AGENT_TOKEN" https://api.whatsapp.com/agent/v1/media/<ID>` for `<ID>` in `1`, `0`, `000000000000000`, `wa-agent-doctor-probe`. Record status and `error.code` for each. The chosen `PROBE_MEDIA_ID` is one that answers **404**; an id that answers 400/100 with a *good* token is rejected because the client would call it dead.
  2. **Bad token.** Same request with `Authorization: Bearer ${WHATSAPP_AGENT_TOKEN}x` and with a well-formed but unknown token. Expect 401 or 400/100. Record both.
  3. **No side effect on a poller.** With `wa-agent recv --follow` running in another terminal, repeat step 1 three times; the poller must keep running and must not exit 9. Record it.
  4. **Rate limit.** Note whether the probe consumes the `media_get` window (12 a minute) visibly, e.g. by 13 calls in a minute answering 429. One doctor run makes one call, so this only needs to be known, not avoided.
  5. **Gemini.** `curl -sS -o /dev/null -w '%{http_code}\n' -H "x-goog-api-key: $GEMINI_API_KEY" 'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1'` with the good key and with `${GEMINI_API_KEY}x`. Expect 200 versus 400/403; record which.
  6. **OpenRouter.** `curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $OPENROUTER_API_KEY" https://openrouter.ai/api/v1/key` with the good key and with `${OPENROUTER_API_KEY}x`. Expect 200 versus 401; record which, and record it for the *kind* of key actually used for transcription (an inference key, not a management key), since a key valid for transcription that `/key` refuses would make `doctor` fail a working setup. No credits are spent (a metadata read).
- Test: the recorded results, in this file. If step 1 finds **no id** that answers 404 with a good token, or step 2 cannot be told apart from step 1, the plan is amended before Phase 5: the token line falls back to "present and well-formed; **not verified**, no side-effect-free endpoint answers differently for a dead token", which passes but says so, and the lead is told before anything merges. If step 5 or 6 does not tell a good key from a bad one, that provider's line falls back to `optional` "present, not verified" and never `fail`.

### Phase 2 — The failure code, the client probe and the module
**Status:** Done — `doctor_failed` (15) in `errors.py` plus its `docs/errors.md` row (moved up from Phase 3 so the docs-sync check stays green), `WhatsApp.probe_token` with `PROBE_MEDIA_ID` / `PROBE_ACCEPTED` constants, and `wa_agent/doctor.py` with a table-driven `probe_key` for both providers
- Files: `wa_agent/errors.py:21-24` (docstring list, add `15   doctor_failed`), `wa_agent/errors.py:40-54` (`CODES`, add the row before `internal`); `wa_agent/client.py:24-26` (constants `PROBE_MEDIA_ID`, `PROBE_ACCEPTED`), `wa_agent/client.py:161` (new method `probe_token` beside `download`, which shares `_error_code`, `RETRYABLE_STATUS` and the limiter); new `wa_agent/doctor.py` (imports `KEY_ENVS`, `PROVIDERS` and `api_key` from `wa_agent/transcribe.py:28-32`, `55`; `transcribe.py` itself is not edited).
- Change:
  - `errors.py`: `"doctor_failed": Error(15, "one or more setup checks failed; each line above says what to do", False)`. The message must not contain a traceback, an HTTP body or a provider name (the existing check).
  - `client.py`: `probe_token(self)` does `self.limits.acquire("media_get")`, `self._session.request("GET", f"{self.base}/media/{PROBE_MEDIA_ID}", headers=self._headers, timeout=15)`, maps transport errors to `platform_unavailable`, then the table from Approach. Additive only: `_request`, `_checked`, `poll`, `download`, `send_iter` and every return shape are unchanged. `PROBE_MEDIA_ID` starts as `"1"` and is set from Phase 1.
  - `doctor.py`: `Check = namedtuple("Check", "name status message fix")`; `MIN_PYTHON = (3, 10)`; `run_checks(token_file=None, state_dir_override=None, profile=DEFAULT_PROFILE, env=None, session=None, python_version=None)` returning the six checks in the table's order; `render(checks)` returning the lines; `failed(checks)`. The token check reads `WHATSAPP_AGENT_TOKEN` then the file itself (it needs to say which source won and to catch internal whitespace, neither of which `resolve_token` reports), skips the network when there is no usable token, and otherwise builds `WhatsApp(token, session=session)` and calls `probe_token()`, turning `AuthError` / `platform_unavailable` / `platform_rejected` into the lines in the table. `probe_key(provider, key, session)` is one table-driven function for both providers (URL, header builder, rejected statuses per the key-probe table): a `GET` through the same injected session, `transport_errors` taken from the session as `client.py:69` does, returning `accepted`, `rejected` or `unverified`; the caller turns that into a line. Only fixed strings and the variable's *name* reach a line. State-dir writability uses `state.state_dir(..., create=False)`; a `WhatsAppError` from a bad `--profile` becomes a `fail` line, not a traceback.
- Test: added in Phase 4.

### Phase 3 — The subcommand and the docs
**Status:** Done — `doctor` subparser, dispatch and `_doctor` in `cli.py`; README row and a pointer under "When something fails"; a `doctor` example in `docs/errors.md` (its table row landed in Phase 2)
- Files: `wa_agent/cli.py` (new `_doctor` beside `_errors` at `cli.py:420`; parser entry beside `p_err` at `cli.py:377`; dispatch branch in `main`, `cli.py:402-410`); `docs/errors.md` (table row, after `transcription_failed`, before `internal`; and the "For a script" section gets a two-line `doctor` example); `README.md` (command table at `README.md:90-97`, a row for `doctor`, plus one sentence in "Get a token" or "When something fails" pointing at it); `docs/INDEX.md` needs no change.
- Change: `_doctor(args, env=None, session=None)` builds the arguments for `run_checks` from the global options only, prints `render(checks)` to stdout, and `raise WhatsAppError("doctor_failed", f"{n} of {total} checks failed")` when any check failed. The `main` dispatch adds `elif args.func is _doctor: _doctor(args, env=env, session=session)`. `doctor` takes no options of its own. Output shape, one line per check and a fix line under a failure:
  ```
  ok        python           3.11.14
  FAIL      token            no token in WHATSAPP_AGENT_TOKEN and no --token-file
            fix: export WHATSAPP_AGENT_TOKEN, or pass --token-file PATH before the subcommand
  optional  gemini key       GEMINI_API_KEY is not set; only needed for --provider gemini
  optional  openrouter key   OPENROUTER_API_KEY is not set; only needed for --provider openrouter
  ok        state dir        /…/wa-agent/default is writable
  FAIL      creator          none recorded yet
            fix: run `wa-agent recv` and message your agent once; until then `send` needs --to
  ```
  The README row must be `` | `doctor` | … | `` so the existing command-versus-`--help` check finds it.
- Test: added in Phase 4.

### Phase 4 — The smoke check
**Status:** Done — `section("doctor")` and `section("client.probe_token")` in `tests/smoke.py`; six mutations (probe hits `/updates`, unknown key status read as accepted, token echoed, docs row removed, state dir created, unreachable token read as good) each turned the check red, then were reverted
- Files: `tests/smoke.py`. A new `section("doctor")` after the `recv --download` block (before `section("module entry point")`, `tests/smoke.py:1144`), reusing `FakeSession`, `FakeResponse`, `FakeTransportError` and `run_cli` (`tests/smoke.py:59`, `235-265`). The `--help` list at `tests/smoke.py:166` gains `"doctor"`.
- Change: scenarios, each on a temp `HOME`/`--state-dir`, each asserting the recorded `session.calls`:
  1. all good (404 on the token probe, 200 on Gemini, 200 on OpenRouter, a creator file present): exit 0, six lines, no `FAIL`;
  2. **`/updates` is never requested** in any scenario: `assert not any("/updates" in c["url"] for c in session.calls)`, and the token check accounts for exactly one WhatsApp call, a `GET` whose url ends `/media/` + `client.PROBE_MEDIA_ID`;
  3. dead token, both `401` and `400/100`: token line `FAIL`, fix names getting a fresh token, exit 15;
  4. unreachable (`FakeTransportError`, `429`, `503`): token line `FAIL`, message says "could not reach", never "accepted";
  5. an unexpected `403`: `FAIL` with "unexpected", not "accepted";
  6. no token: `FAIL`, zero WhatsApp calls; a token containing an internal newline: `FAIL`, zero calls;
  7. per provider, run for gemini and for openrouter with the other absent and then present: key absent → that line `optional`, **zero** calls to that provider, exit 0 when the rest pass; rejected (gemini 400 and 403, openrouter 401 and 403) → `FAIL`, exit 15; unverifiable (503, 429, transport error) → `optional`, exit 0; an unknown status (404) → `optional`, never "accepted". A rejected key on one provider fails the run even when the other is accepted. A whitespace-only key counts as absent (the `api_key` rule);
  7b. probe shape: each key probe is exactly one `GET` with no body, the gemini url is the models listing and the openrouter url is `https://openrouter.ai/api/v1/key`, the credential travels only in the header (`x-goog-api-key` / `Authorization: Bearer`), neither URL contains the key, and neither url matches `generateContent`, `audio/transcriptions` or `/chat`; `wa-agent doctor --key-env X` exits 2;
  8. state dir: existing and writable, absent-but-creatable, absent-under-an-unwritable-parent (skipped when `os.geteuid() == 0`), a path that is a file; and after every run the temp tree is identical to before, including that an absent directory is still absent;
  9. creator missing: `FAIL` with the `recv` fix;
  10. secrets: distinct made-up strings for the token, the Gemini key and the OpenRouter key are absent from stdout and stderr in every scenario above (pass, fail, unreachable), with `WHATSAPP_AGENT_DEBUG=1` too, including a scenario where the session raises a transport error whose text contains the key;
  11. `MIN_PYTHON` parsed against `requires-python` in `pyproject.toml`; `run_checks(python_version=(3, 9, 0))` fails the python line;
  12. `client.probe_token` unit rows: 404 and 200 return, 401 and 400/100 raise `AuthError`, 403 raises `platform_rejected`, 429/503/transport raise `platform_unavailable`, and the request carries the bearer header and is paced through the limiter.
- Test: `python3 tests/smoke.py` passes; deleting the `doctor_failed` docs row makes the "documented codes" section fail naming it (run once by hand, then restore).

### Phase 5 — Reconcile with the probes, and run it for real
**Status:** Not started — **post-merge**, needs Phase 1's results. Ships as a follow-up PR (or a direct amendment the lead approves) that only edits constants and this plan.
- Files: `wa_agent/client.py` (constants only), `wa_agent/doctor.py` (the Gemini and OpenRouter rejected-status sets), this plan (Probe results, criteria).
- Change: set `PROBE_MEDIA_ID` and the accepted/dead status sets from the recorded results; if Phase 1 showed the fallback is needed, apply it and update the token line's wording and the smoke scenarios that assert it. Then, post-merge, with the owner's demo agent: (1) `wa-agent doctor` before any state exists shows `FAIL creator`, `ok token`, `ok state dir` (creating nothing); (2) `wa-agent recv --follow` running in a second terminal, then `wa-agent doctor` in the first, three times, and the poller neither errors nor exits 9; (3) `wa-agent doctor` with the token corrupted by one character shows the dead-token fix.
- Test: the two manual runs above, with their output pasted into the review checklist.

## Probe results
_Not run, by design: no live calls from this lane (WhatsApp, Gemini or OpenRouter). After merge, Phase 1 fills this in: a table of `request → status → error.code` for each step, dated, with no token or body._

## Risks
- **The probe status mapping is wrong, and it ships unconfirmed.** Mitigated by Phase 1 (post-merge) and by keeping the mapping in constants. Until Phase 1 is done the PR body says the probe is unverified against the live platform. The worst case is `400/100` on a good token for a malformed id, which the existing dead-token rule would read as a dead token; the chosen id must answer 404.
- **`doctor` is not offline.** A real run makes a real, free, side-effect-free request to the platform and to every provider whose key is set in the environment (that is the check). Anyone running it in a shell that holds live keys, this lane included, must expect those calls; the README row says so, and manual runs of the command from this lane use an empty environment. The smoke check never reaches the network.
- **The probe spends a `media_get` request** (12 a minute, shared with `media get`). One per run; a `media get` loop running at the same moment could see a 429 once. Recorded in Phase 1 step 4, not avoided.
- **A key endpoint might not reject a bad key the way generation does.** Gemini's models listing and OpenRouter's `/api/v1/key` are both unconfirmed for a bad key. Phase 1 steps 5 and 6 confirm; a provider that does not distinguish falls back to "present, not verified", `optional`.
- **OpenRouter's `/key` may refuse a key kind that transcription accepts** (or the reverse), which would make `doctor` fail a working setup. Phase 1 step 6 uses the kind actually used for transcription; until then the PR body says the OpenRouter line is unverified live.
- **Adding a public method to `WhatsApp`** widens the library API by one method. It changes nothing Hisab calls, but it is a shared file, so the lead approves it before Phase 2.
- **`os.access` is advisory** on some filesystems (network mounts, ACLs), so a `ok state dir` is a strong hint, not a guarantee. The message says "writable", and a real write failure still surfaces as its own code on first use.

## Out of scope
- `--json` output and any auto-fix (the lead's instruction: only if the plan argues for it and he agrees; this one does not).
- Checking the coding agent CLI, folders, write paths or sessions: those belong to the relay lane.
- Touching what `send`, `recv`, `media`, `transcribe` print or return, `recv --json`, or the return shapes of `poll`, `send_iter`, `download` and `Store`.
- A version bump, a promote PR, or a `CHANGELOG.md` entry: releases are the owner's call and bump once at the promote (`.agents/rules/releases.md`).
- Any live call to the WhatsApp, Gemini or OpenRouter endpoints from this lane. (The OpenRouter path was read from its documentation page, not by calling the API.)
- A `--provider` or `--key-env` option on `doctor`: both providers are always checked, each at its default variable.
- Any change to `.env.example` or `wa_agent/transcribe.py`: `doctor` reads only variables `.env.example` already lists (`WHATSAPP_AGENT_TOKEN`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`) and imports, but does not edit, the transcription module.
