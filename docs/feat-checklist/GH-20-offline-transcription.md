---
type: FeatChecklist
slug: GH-20-offline-transcription
issue: 20
timestamp: 2026-09-19T00:00:00Z
---

# GH-20-offline-transcription — acceptance checklist   (15 proven · 2 manual · 0 failing)

- [x] The `local` extra is declared and named — `pyproject.toml` has `local = ["faster-whisper>=1.2,<2"]`, the README shows `pip install "wa-agent[local]"`, and the declared-versus-mentioned extras check passes (`python3 tests/smoke.py`)
- [x] The default install does not pull the engine, and the check proves it — `[project] dependencies` is `requests` alone (smoke asserts none of `faster-whisper`, `ctranslate2`, `onnxruntime`, `huggingface` appears), and a fresh interpreter that imports every module and calls `check_local` leaves `faster_whisper` out of `sys.modules`
- [x] Smoke passes without the extra installed — the real `faster_whisper` is not in the `.venv`; the check fakes it (signatures read from the 1.2.1 wheel) and runs "not installed" with `sys.modules["faster_whisper"] = None`
- [x] `transcribe(path, provider="local")` returns the words as a plain `str` with no key, no session and no request (fake engine; the guard session records zero calls; the engine is built from an existing directory, `cpu`, `int8`, `vad_filter=True`)
- [x] `local` is never chosen by absence — no `--provider` and no `GEMINI_API_KEY` is still exit 12, with the extra present and a model on disk; also run by hand: `env -i … wa-agent transcribe note.ogg` → `error [no_transcription_key]`, exit 12
- [x] The download is explicit and says its size first — `model pull` prints `downloading the "base" Whisper model, about 150 MB, to …` before the fake download starts (the fake reads the output at the moment it is called), goes through `<size>.partial`, is a no-op when present, and a failed or incomplete download exits 13 leaving nothing ready
- [x] Nothing downloads during `recv` — no model on disk: one up-front warning, the note delivered `transcribed: false` with `transcription_error: "local_not_ready"`, and the fake engine records zero downloads and zero constructions; a directory without `tokenizer.json` is refused before the engine is built
- [x] A transcript carries its engine — a local `recv --json` note has `transcribed_by: "local:base"`; Gemini and OpenRouter lines carry no such key and no tag on stderr; apart from the tag the local message equals the Gemini one; `transcribe()` still returns a plain `str`
- [x] Failures are coded — empty or whitespace output and an engine that raises are 14 (reason in `detail`, none in the message); an extra or model that is missing is 16 naming the fix, also run by hand (`wa-agent transcribe … --provider local` in an empty environment → exit 16, `pip install "wa-agent[local]"`)
- [x] `--key-env` with `local` and a size outside tiny, base, small (`medium`, `base.en`, `large-v3`) are `bad_usage`, refused by `recv` before its first poll (no request made)
- [x] `state.models_dir` resolves `$XDG_DATA_HOME/wa-agent/models`, else `~/.local/share/wa-agent/models`, never the working directory (resolved from a temp cwd that stays empty); looking creates nothing, and a refused pull or transcription creates nothing
- [x] Doctor has a `local engine` line that is never `FAIL` — `optional` without the extra, `optional` with no whole model (a `.partial` or a directory missing a file is not one), `ok` naming the sizes; no request, no engine built, nothing written (tree snapshot equal before and after); also run by hand in an empty environment
- [x] The docs say plainly what the engine is bad at — README and `docs/errors.md` both name Urdu, Roman Urdu and code-switching, say the failure looks like success, and say why there is no `.en` model; `local_not_ready` has its row and the documented-codes check passes
- [x] No OpenAI-server string anywhere — no `OPENAI_`, no `api.openai.com`, and `openai` appears only on the `MODELS` line, across `wa_agent/`, `README.md`, `.env.example` and `docs/errors.md`
- [?] **Post-merge, owner + lead — the engine on a real machine.** Not run from this lane (no network, no model download). In a fresh virtualenv:
  1. `pip install "wa-agent[local]"`, then `wa-agent doctor`: the `local engine` line says the extra is installed and no model is downloaded (`optional`).
  2. `wa-agent model pull base`: the size line (about 150 MB) appears first, the download completes, `~/.local/share/wa-agent/models/base/` holds `model.bin`, `config.json` and `tokenizer.json` and no `base.partial`; `doctor` now says `ok`, `base downloaded`. Confirm the real sizes of `tiny`, `base` and `small` against the table (about 75, 150 and 500 MB) and correct `local.SIZES` if they are off.
  3. With the network off, `wa-agent transcribe <clear english note>.ogg --provider local` prints the words and exits 0, with the caveat line on stderr. Then `recv --transcribe --provider local` on the same note: `transcribed_by: "local:base"` in the JSON.
  4. Try an Urdu or mixed note and look at what comes out: it should confirm the documented weakness, and the README's wording should match what you see.
- [?] **Python 3.10** — not run from this lane (only 3.11 is installed here); the CI matrix (3.10 to 3.13) runs it first.
- [x] Repo check passes — `python3 tests/smoke.py` under `env -i` in the repo's `.venv`, all sections, exit 0

## Conventions

- **Failures are codes** — one new code, `local_not_ready` (16), registered, documented and agreeing across `CODES`, `docs/errors.md` and the `errors` command; its fixed message carries no traceback, path or provider body.
- **Transport** — untouched: dedup, the offset after a batch, backoff and dead-token exit live in code this change does not edit; `recv` still delivers a note whose transcription failed, marked, and the cursor still advances (asserted for the not-ready case).
- **Voice notes are transcribed before the agent sees them; a failure is reported, never handed on as speech** — an empty or failed local result is 14 or 16 and the message carries `transcribed: false`, never invented words.
- **Secrets** — the local provider has none; `--key-env` with it is refused.
- **Privacy** — the staged diff was read against `.agents/rules/privacy.md`: fake fixtures only, no path, host or name from a personal setup. The one match of a scan for `token=` is a parameter name in the recorded faster-whisper signature.
- **Tests** — every new unit is exercised: `local.py` (readiness, pull, run), `state.models_dir`, `check_usage`, the CLI paths, doctor's line, and the default-install proof.
- **Docs** — README, `.env.example` and `docs/errors.md` are true and agree with `--help`.

## Findings

FINDING-01 · Minor · `AGENTS.md` (repo map) — the map lists five modules and calls `cli.py` "stubs until their own ticket lands"; `transcribe.py`, `doctor.py` and now `local.py` are missing and the stub line has been untrue since #4. Pre-existing drift that `local.py` widens. Not fixed here: it is outside this ticket's diff, and a project instruction file is not something to change in passing.
