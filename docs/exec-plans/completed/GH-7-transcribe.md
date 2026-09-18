---
type: ExecPlan
slug: GH-7-transcribe
issue: 7
status: completed
open_questions: none
---

# feat: transcribe — voice notes to text          ✅ COMPLETED — 2026-09-18

## Problem

[#7](https://github.com/mhmzdev/whatsapp-agent-cli/issues/7). A voice note reaches a caller as a media id and nothing else, so every consumer that wants the words has to fetch audio, find a provider and handle its failures. hisab already wrote that code once. This is the last feature before the publish gate.

The five decisions from the grilling (2026-09-17) are recorded on the issue and are not reopened here: no config file; Gemini only, keyed by `GEMINI_API_KEY`; the fetched audio is deleted immediately; the message keeps its shape and gains `text.body`; a failed transcription never costs the message.

## Approach

**The `[transcribe]` extra is dropped, and this is a change from the issue's wording.** Gemini's REST endpoint takes inline audio and needs nothing but an HTTP call, so `google-genai` — 30-odd megabytes of SDK to post one request — buys nothing here. Transcription therefore works in the default install with only a key, and the only extra that will ever exist is `[local]` for offline transcription (#20). This also means the whole path is testable with the same injected fake session as everything else, rather than by monkey-patching an SDK.

hisab's `hisab/transcribe.py` is the prior art for the prompt and for one rule worth carrying: an empty response is a failure, not an empty transcript.

**`transcribe.py` is a module, not a method on the client.** The WhatsApp client speaks to one host with one token; transcription speaks to a different host with a different key. Folding it in would blur that. It takes an injectable session like the client does, and raises the same `WhatsAppError` codes.

**Three new codes**, because the actions differ: `no_transcription_key` (12) — nothing to do but set the key; `transcription_unavailable` (13) — the provider was unreachable, so a retry may work; `transcription_failed` (14) — the provider answered but produced nothing usable, so it will not.

**Inside `recv --transcribe`,** an audio message is fetched to a temp file, transcribed, and the file deleted in a `finally`. The message is then given `text.body` and `transcribed: true`, or `transcribed: false` with `transcription_error` naming the code. The store records the transcript as the message's text, so a quoted-reply lookup returns words rather than `<audio media-1>`.

**Cost is made visible.** Each voice note is a billed call, so `recv --transcribe` prints one line to stderr per transcription with the message id. A caller who leaves `--follow --transcribe` running overnight can see what it spent from the log, and the flag stays opt-in.

## Success criteria

- [x] `whatsapp-agent transcribe note.ogg` prints the transcript and nothing else — `verify: python3 tests/smoke.py`
- [x] The request carries the audio inline with its mime type and the prompt, to the model named by `--model` — `verify: python3 tests/smoke.py` asserts the posted body
- [x] `recv --transcribe` gives an audio message `text.body` and `transcribed: true`, leaving `type` and the audio object untouched — `verify: python3 tests/smoke.py`
- [x] The fetched audio is deleted whether transcription succeeds or fails, and never lands in the media directory — `verify: python3 tests/smoke.py`
- [x] A failed transcription still delivers the message, marked `transcribed: false` with the code, warns on stderr, and does not stop `--follow` — `verify: python3 tests/smoke.py`
- [x] No key exits 12 naming `GEMINI_API_KEY`; an unreachable provider is 13; an empty or refused response is 14 — `verify: python3 tests/smoke.py`
- [x] A provider error is never returned as if it were speech — `verify: python3 tests/smoke.py` feeds an error body and asserts the message is marked failed, not transcribed
- [x] The store records the transcript as the message's text — `verify: python3 tests/smoke.py`
- [x] The default install needs no extra for Gemini; `pyproject.toml` no longer declares `transcribe` — `verify: python3 -c "import tomllib;assert 'transcribe' not in tomllib.load(open('pyproject.toml','rb'))['project']['optional-dependencies']"`
- [x] Every transcription prints one stderr line naming the message id, so spending is visible — `verify: python3 tests/smoke.py`
- [x] Repo check passes on 3.10 through 3.13 — `verify: python3 tests/smoke.py` locally, the CI matrix on the PR
- [?] Manual: a real voice note comes out as words — `verify: manual 1. export GEMINI_API_KEY and WHATSAPP_AGENT_TOKEN 2. whatsapp-agent recv --follow --json --transcribe 3. send a voice note from the phone, in Urdu and English mixed 4. the object carries text.body with what was said, transcribed: true, and no audio file is left in the state directory`

## Phases

### Phase 1 — The transcription module
**Status:** Done
- Files: `whatsapp_agent/transcribe.py` (new), `whatsapp_agent/errors.py`, `docs/errors.md`, `tests/smoke.py`
- Change: `transcribe(path, *, model=None, key=None, key_env="GEMINI_API_KEY", language=None, session=None, env=None)` posting inline base64 audio to Gemini's `generateContent`, with hisab's prompt rule (keep the spoken language, digits as digits, transcript only). Empty text is `transcription_failed`. Three codes added, each with a documented row.
- Test: the posted body's shape; a good response; an empty response; a 500; a missing key; a mime type derived from the extension.

### Phase 2 — The `transcribe` command
**Status:** Done
- Files: `whatsapp_agent/cli.py`, `tests/smoke.py`
- Change: the stub becomes real — `--provider` (only `gemini` for now, so `--provider local` fails with a pointer to #20), `--model`, `--key-env`, `--language`. Prints the transcript and nothing else.
- Test: through `cli.main` with a fake session; stdout is exactly the transcript; a bad provider is a usage error naming #20.

### Phase 3 — `recv --transcribe`
**Status:** Done
- Files: `whatsapp_agent/cli.py`, `tests/smoke.py`
- Change: audio messages are fetched to a `TemporaryDirectory`, transcribed, and the directory removed in a `finally`. Success adds `text.body` and `transcribed: true`; failure adds `transcribed: false` and `transcription_error`, warns, and carries on. The store records the transcript. One stderr line per transcription.
- Test: a batch of one audio and one text message proves only the audio is fetched; the temp file is gone afterwards; the media directory is untouched; a failing provider still delivers and `--follow` keeps going.

### Phase 4 — Packaging, docs, checklist
**Status:** Done
- Files: `pyproject.toml`, `README.md`, `docs/feat-checklist/GH-7-transcribe.md`
- Change: drop the `transcribe` extra; the README documents the key, the flags and what a transcribed message looks like, and stops promising an extra that no longer exists.
- Test: the README check already asserts that every extra `pyproject.toml` declares is mentioned; it gains the reverse assertion so a dropped extra cannot linger in the prose.

## Risks

- **Gemini's request shape changing.** Hand-rolling the REST call means the SDK is not absorbing that for us. It is one endpoint and the check pins the body we send, so a break is loud rather than subtle.
- **A long voice note timing out.** The call gets its own generous timeout, and a timeout is `transcription_unavailable` — retryable — rather than a failed transcript.
- **Billing surprise.** `--transcribe` is opt-in and every call prints a line. Nothing transcribes without being asked.

## Out of scope

- Offline transcription — #20.
- Any provider beyond Gemini; `--provider` exists so a second one is additive.
- Translating. The prompt keeps the language as spoken, including Roman Urdu.

## What actually happened (2026-09-18)

Four phases as planned. The `[transcribe]` extra is gone: a spike against the live
endpoint before any code was written confirmed Gemini takes inline base64 audio over
an ordinary JSON POST — 4.7s with nothing but the standard library — so the SDK would
have bought a dependency and lost the fake-session testability.

Three things the work surfaced:

1. **The check's "no provider name in a message" rule was wrong here.** It came from hisab, where a ledger's user should never read "openrouter said…". A developer who must set `GEMINI_API_KEY` has to be told which variable, so provider names are now allowed in messages and the rule keeps what matters: no traceback, no HTTP body, no provider's raw words.
2. **The store was recording `<audio media-1>` for a transcribed voice note.** `_text_of` keyed on the message type rather than on whether words were present, so a quoted-reply lookup would have returned a placeholder. It now records whatever body the message carries.
3. **`--language` is a prompt hint, not a parameter.** Gemini takes no language field on this endpoint, so the hint is appended to the prompt. Verified in the check by asserting the hint reaches the prompt text.

Verified live through the installed command: a synthesized voice note transcribed in 3.6s with digits as digits, a missing key exited 12 naming the variable, and `--provider local` exited 2 pointing at #20.
