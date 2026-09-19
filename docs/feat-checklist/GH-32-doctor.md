---
type: FeatChecklist
slug: GH-32-doctor
issue: 32
timestamp: 2026-09-19T00:00:00Z
---

# GH-32-doctor — acceptance checklist   (15 proven · 3 manual · 0 failing)

- [x] `wa-agent doctor` prints one line per check with `ok` / `FAIL` / `optional` and a `fix:` line under every failure — `python3 tests/smoke.py` (six lines in order; every `FAIL` has a fix)
- [x] It exits non-zero when any check fails, so it works in a script — exit `15` (`doctor_failed`) on any `FAIL`, `0` otherwise; the failure is the fixed one-line message and never a traceback
- [x] Checking the token makes no request to `/updates`, proven with a fake session — every scenario asserts no recorded call matches `/updates` and every call is a bodyless `GET`; the token check is exactly one `GET /media/<PROBE_MEDIA_ID>`
- [x] A missing provider key is `optional`, not a failure — gemini and openrouter separately, blank counts as absent, and an absent key makes no request to that provider; both absent still exits 0
- [x] A present key is probed: rejected is `FAIL` (gemini 400/401/403, openrouter 401/403); unreachable, 429, 5xx or an unknown status is `optional`, never "ok"; a rejected key on one provider fails the run whatever the other says
- [x] The probes are metadata GETs — Gemini's model list, OpenRouter's `/api/v1/key`; the credential travels in a header, never in the url, and no url touches a generation, audio or chat endpoint
- [x] A dead token (401, or 400 with `error.code` 100) fails with a fresh-token fix; an unreachable platform (transport, 429, 503) fails with "could not reach"; an unknown answer (403, 400/33) fails with "unexpected"; none is reported as a good token
- [x] `doctor` writes and creates nothing — byte-and-mode snapshots of a temp tree are identical before and after, including an absent state directory that stays absent; unwritable parent, unwritable directory (off root), a file in the way and a bad `--profile` all report a `FAIL` line
- [x] Neither the token nor either key ever appears in stdout or stderr, with and without `WHATSAPP_AGENT_DEBUG=1`, including when a transport error's own text contains them
- [x] `doctor` takes no options: `--key-env` is refused (exit 2) and is not in `doctor --help`
- [x] `MIN_PYTHON` agrees with `requires-python`; an older interpreter fails the python line
- [x] `doctor_failed` is registered and documented — `CODES`, `docs/errors.md` and the `errors` command agree; removing the docs row makes the check fail naming the code (run by hand, restored)
- [x] The README documents `doctor` and the README-versus-`--help` check finds it
- [x] Nothing existing changed shape — every existing smoke section passes unmodified apart from `doctor` joining the `--help` list; `probe_token` is additive and `transcribe.py` is untouched
- [x] Repo check passes — `python3 tests/smoke.py` in the editable venv after merging `origin/develop` (0.2.0), 27 sections, "all checks passed". Six mutations (probe on `/updates`, an unknown key status read as accepted, the token echoed, the docs row removed, the state directory created, an unreachable token read as good) each turn it red
- [?] **Post-merge, owner + lead — the status mappings confirmed against the live services.** Not run from this lane (no live calls; the demo token is shared). Each with a good and a bad credential; record status and `error.code` only, never a token or key. Steps are in the plan under Phase 1, "Probe results":
  1. WhatsApp, `GET /media/<id>` for candidate ids (`1`, `0`, `000000000000000`, `wa-agent-doctor-probe`) with a good token: pick the id that answers 404. An id that answers 400/100 with a *good* token is rejected, because `probe_token` would call it dead. Then a bad token: expect 401 or 400/100.
  2. Gemini, `GET .../v1beta/models?pageSize=1` with `x-goog-api-key`: good key 200, bad key 400/403?
  3. OpenRouter, `GET https://openrouter.ai/api/v1/key` with a bearer: good key 200, bad key 401? Use the kind of key used for transcription, not a management key.
  4. Whichever provider cannot tell good from bad falls back to "present, not verified" (`optional`), and the plan is amended before it is relied on.
- [?] **Post-merge, owner + lead — `doctor` beside a live poller does not cost it a 409.** With the demo agent: start `wa-agent recv --follow` in one terminal, run `wa-agent doctor` three times in another; the poller keeps running and never exits 9.
- [?] **A real run is not offline.** `doctor` in a shell that holds live keys makes real, free metadata requests to the platform and to every provider whose key is set (the README says so). A terminal check for a human: `env -i HOME=$HOME PATH=$PATH wa-agent doctor` shows the token line failing and both keys optional, with no request made.

## Conventions

- **Transport invariants** — never `/updates`, so it cannot steal a poll or take a 409; dead-token semantics stay aligned with `errors.py` (401, or 400 with `error.code` 100); the probe goes through the `media_get` limiter and does not retry; nothing about dedup, the cursor or chunking is touched.
- **Failures are codes** — one new registered, documented code, `doctor_failed` (15, not retryable), with a fixed message free of traceback, HTTP body and provider name; the detail is "N of 6 checks failed".
- **Secrets** — read only from the environment or `--token-file`; every line is fixed text plus a variable name; no exception text is echoed; asserted for all three secrets in every scenario shape.
- **Read-only default** — `doctor` grants nothing and writes nothing; the state directory is resolved with `create=False` and tested with `os.access`.
- **Privacy** — the diff and commit message read against `.agents/rules/privacy.md`: no host, token, id, folder or personal detail; fixtures use made-up strings; the accidental live Gemini call stays out of every artifact.
- **Tests** — every new unit (`probe_token`, `probe_key`, each check, `render`, `failed`, `_doctor`) is exercised, plus the mutations above.
- **Docs** — README and `docs/errors.md` updated; `.env.example` needs no change; `AGENTS.md` still true (its repo map already omits several modules and is not this change's to fix).
- **Not exercised locally** — Python 3.10, which CI runs (3.10 to 3.13); the new code parses as 3.10 syntax and uses nothing added since.

## Findings

**FINDING-01 · Minor · `wa_agent/doctor.py:54`** — a module-level `assert set(KEY_PROBES) == set(PROVIDERS)` runs when `doctor` is imported, and `cli.py` imports it, so adding a provider to `transcribe.PROVIDERS` without a probe would make every command (`send`, `recv`, …) die at import rather than only `doctor`. The smoke check already asserts the same parity, and an `assert` disappears under `-O`. Suggest deleting the line and leaving the check to smoke.

**FINDING-02 · Minor · `wa_agent/doctor.py` `probe_key` / `check_key`** — a key pasted across two lines makes `requests` raise `InvalidHeader` (a `RequestException`) before any request is sent, which `probe_key` reads as a transport error, so the line says "could not be reached or gave no clear answer" for what is a paste error. The token check already catches internal whitespace before probing; a key deserves the same. Suggest a whitespace check in `check_key` that reports "contains whitespace inside it" as a `FAIL` with no request.
