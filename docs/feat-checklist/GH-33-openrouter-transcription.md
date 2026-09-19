---
type: FeatChecklist
slug: GH-33-openrouter-transcription
issue: 33
timestamp: 2026-09-19T00:00:00Z
---

# GH-33-openrouter-transcription — acceptance checklist   (11 proven · 1 manual · 0 failing)

- [x] `wa-agent transcribe note.ogg --provider openrouter` prints the transcript and nothing else, with only `OPENROUTER_API_KEY` set — `python3 tests/smoke.py` (fake session: stdout is exactly the transcript, stderr empty)
- [x] `recv --transcribe --provider openrouter` keeps the message's shape exactly as the Gemini path does — the delivered message compares equal to the Gemini run's; the store records the words; no audio is kept
- [x] The default provider is still `gemini`, and both keys exported never changes which one is used — both keys, no `--provider` calls the Gemini url with the Gemini key; only `OPENROUTER_API_KEY` set with no `--provider` exits 12 and sends nothing
- [x] A missing key names the variable for the chosen provider, and `no_transcription_key`'s message no longer mentions a provider — asserted for gemini, openrouter and `--key-env`; also run by hand in a terminal with an empty environment (`detail: OPENROUTER_API_KEY is not set`, exit 12, no network)
- [x] `docs/errors.md` agrees — the row names both variables, and the documented-codes check still passes
- [x] The OpenRouter request shape is pinned by a fake-session test — method, url, bearer header, no key in the url, form `model` and `language`, file as bytes, no JSON body
- [x] The failure mapping matches Gemini's — 503, 429, 408 and a transport error are 13; a 4xx, non-JSON, no `text`, empty or null `text` are 14; no key material in any message or detail
- [x] An unknown provider is refused — `transcribe --provider local|openai` is `bad_usage` (exit 2); `recv --transcribe --provider local` fails before any request
- [x] No OpenAI provider, endpoint or key name anywhere in the package — no `OPENAI_`, no `api.openai.com`, `openai` not in `PROVIDERS`, and the only line mentioning it is the `MODELS` constant
- [x] `.env.example` and the README document `OPENROUTER_API_KEY` and `--provider`; the README never shows the default model id
- [x] Nothing existing changed shape — every existing smoke section passes unmodified; the library names (`DEFAULT_MODEL`, `DEFAULT_KEY_ENV`, `GEMINI_URL`, `api_key`, `mime_for`) still import
- [?] **Post-merge, owner + lead — the OpenRouter request confirmed once against the live endpoint.** Not run from this lane (no live calls; the demo token is shared). With a real `OPENROUTER_API_KEY` and one short voice note:
  1. `wa-agent transcribe note.ogg --provider openrouter` prints the words, exit 0: is `openai/whisper-1` accepted? If not, record the id that is and set `MODELS["openrouter"]` to it.
  2. Repeat with `--language ur` and `--language urdu`: which does the provider take? Correct the `--language` help.
  3. `OPENROUTER_API_KEY=wrong wa-agent transcribe note.ogg --provider openrouter` comes out as `error [transcription_failed]` (14), not a retryable code. (The lead expects a 401 → 14.)
  4. With both keys exported and no `--provider`, Gemini is used.
- [x] Repo check passes — `python3 tests/smoke.py`, all 25 sections

## Conventions

- **Failures are codes** — no new code; the changed message stays a registered, documented one, and no traceback, HTTP body or provider name is in it.
- **No key material** — never printed, never in a url; the check asserts a distinctive key string is absent from every failure's message and detail.
- **Transport / voice notes** — a failed transcription is still delivered marked, never handed on as speech; audio is still deleted or kept only by `--download`, as before.
- **Provider explicit** — the provider is chosen by the caller and never inferred from a key, per #7's grilling and #33's settled decisions.
- **Privacy** — the diff read against `.agents/rules/privacy.md`: no host, token, id, folder or personal detail; fixtures use made-up keys.
- **Tests** — every new unit (`key_env_for`, `model_for`, `check_provider`, the OpenRouter request and reply) is exercised; two mutations (a provider-naming message, a provider guessed from a key) each fail the check.
- **Docs** — README, `.env.example` and `docs/errors.md` updated; `AGENTS.md` still true (its repo map already omits several modules and is not this change's to fix).

## Findings

**FINDING-01 · Minor · `wa_agent/cli.py` `_recv`** — the provider check runs after the state directory is resolved and the client built, so a missing token is reported before an unknown provider. Harmless (both exit non-zero before any request); noted only because the plan says "before the first poll".

**FINDING-02 · Minor · `wa_agent/transcribe.py` `check_provider`** — provider names are case-sensitive: `--provider OpenRouter` is `bad_usage`. Consistent with today's Gemini behaviour and clear in the message, so left as is.

**FINDING-03 · Minor · `wa_agent/transcribe.py` `_openrouter_request`** — the whole file is read into memory for the multipart body, as the Gemini path already does; bounded by the 16 MB media cap.
