---
type: ExecPlan
slug: GH-20-offline-transcription
issue: 20
status: completed
open_questions: none
---

# feat: offline transcription as an opt-in `local` provider          ✅ COMPLETED — 2026-09-19 (Phase 5 post-merge)

## Problem

[#20](https://github.com/mhmzdev/whatsapp-agent-cli/issues/20). Transcription needs a key, so it costs money per voice note and sends audio to a third party. An offline engine removes both. It is its own ticket because `faster-whisper` is heavy (about 150 MB of dependencies plus a model download) and its quality on the voice notes this was built for (Urdu, Roman Urdu, code-switching) is poor in a way that looks like success: confident, fluent, wrong English.

Corrections to the issue text, since it was filed before #32 and #33:
- The package is `wa-agent`, so the extra is `pip install "wa-agent[local]"`.
- Transcription already has two providers (`PROVIDERS = ("gemini", "openrouter")`, `wa_agent/transcribe.py:28`). `local` becomes the third and the first with no key.
- The owner confirmed that a local Whisper model does not break the "Gemini and OpenRouter only, no OpenAI" policy: that policy is about calling OpenAI's servers. Every OpenAI-server string stays out, and the existing three-way scan in smoke keeps enforcing it (`tests/smoke.py:1076-1086`). Docs say "Whisper", never the maker.

Settled by the issue, not reopened: opt-in only and never chosen because a key is missing; the default install does not pull `faster-whisper` and smoke proves it; the model download is an explicit command that states its size first and nothing downloads during `recv`; the docs say plainly that it is weak on Urdu and code-switching.

## Approach

**A new module, `wa_agent/local.py`, holds everything that touches the engine.** `transcribe.py`'s docstring promises "nothing but the `requests` the package already depends on"; that stays true because `local.py` imports `faster_whisper` only inside the function that runs or pulls a model, never at import time. `transcribe()` dispatches to it for `provider == "local"` exactly as it dispatches to `_gemini_request` or `_openrouter_request`, and the result goes through the same non-empty check (an empty transcript is `transcription_failed`, 14).

**Providers with no key.** `PROVIDERS = KEYED_PROVIDERS + ("local",)` where `KEYED_PROVIDERS = ("gemini", "openrouter")`. `KEY_ENVS` and doctor's `KEY_PROBES` stay keyed to the two keyed providers only: `local` has no key, and inventing a `None` row would make every reader of those tables handle a hole. Everything that iterates keys (`doctor.run_checks`, smoke's parity check) iterates `KEYED_PROVIDERS`; `key_env_for("local")` returns `None`; `--key-env` together with `--provider local` is `bad_usage` (a variable that would never be read is a mistake worth saying out loud). The `no_transcription_key` (12) path is untouched, and `local` never reaches it.

**A new failure code, `local_not_ready` (exit 16, not retryable).** Raised when `--provider local` is asked for and either the `local` extra is not installed or the requested model size has not been downloaded. Its `detail:` line carries the fix (`pip install "wa-agent[local]"` or `wa-agent model pull <size>`). It is the local analogue of 12: `recv --transcribe --provider local` does not fail on it, it warns once up front and marks each voice note `transcribed: false` with `transcription_error: "local_not_ready"`, exactly as a missing key does. A failed model download is the existing `transcription_unavailable` (13, retry: yes), with the reason in `detail`.

**Models are downloaded by one explicit command and never lazily** (ruled, see (b) below). The recv path loads a model from its directory and nothing else: `local.py` builds `WhisperModel(<dir>, device="cpu", compute_type="int8")` from a local path, so there is no repo id to fetch from and no code path that reaches the network. `is_ready(size)` is a file check (`model.bin`, `config.json` and `tokenizer.json` in the model directory), needing no import of the engine, and `run` calls it **before** constructing the model (see "Confirmed from the package source": a path that is not a directory is treated by `WhisperModel` as a size to download). A pull downloads into `<size>.partial` and renames on success, so a half-finished download is never mistaken for a model. A loaded model is cached in the process, so a `--follow` loop pays the load once, not per voice note.

**Silence must not become speech.** Transcription runs with `vad_filter=True` and language auto-detect unless `--language` is given (passed through as a Whisper code such as `ur`, like OpenRouter). Empty output is 14, as everywhere.

**How a transcript carries its engine (ruled).** `transcribe()` keeps returning a plain `str` for every provider; no new type and no new library surface. The caller already knows which engine it asked for, so `recv` writes the tag from its own arguments: `"transcribed_by": "local:<size>"` on a voice note, only when `args.provider == "local"`, with the size being the resolved model (`--transcribe-model` or the default). Gemini and OpenRouter messages stay byte-for-byte what they are today, and an absent key means a remote provider.

**Doctor gets one `local` line, and it never installs, imports the engine, downloads, or writes.** It is `optional` in every case (an optional feature that is not set up never fails a script): extra missing, extra present but no model downloaded, or ok naming the sizes present and where. It looks with `importlib.util.find_spec` and reads directory names only: a size counts as downloaded when its directory exists under `models_dir()` and `is_ready`'s three existence checks pass (stat calls, no file is opened).

**Invariants kept.** Read-only default and session control are untouched (transport layer only). Audio is never kept: `_transcribe_into`'s temp-dir handling is unchanged. A failed transcription is reported, never handed on as speech. Secrets: there are none for this provider. Privacy: no path, model list or fixture from the author's machine; smoke fakes `faster_whisper` entirely.

### Rulings (from the lead; folded in)

**(a) The engine tag.** Simpler than proposed: no `Transcript` type. `recv --json` adds `transcribed_by: "local:<size>"` from its own arguments, local only. `wa-agent transcribe` stdout stays exactly the transcript; on the local path only, one line goes to stderr: `note: transcribed offline by local:base; weak on Urdu and mixed-language speech`. `recv` appends the tag to its `transcribed <id>` stderr line on the local path only.

**(b) The download command and where models live.**
- `wa-agent model pull [SIZE]` (default size: see (c)). `model list` is dropped. `pull` first prints to stderr `downloading the "base" Whisper model, about 150 MB, to <dir>`, then downloads into `<size>.partial` and renames on success, so a half-finished download is never mistaken for a model. It requires the extra (`local_not_ready` if absent, before printing a size it cannot act on). Re-running on a present model says so and downloads nothing. No `--yes`.
- Location: `$XDG_DATA_HOME/wa-agent/models/<size>/`, else `~/.local/share/wa-agent/models/<size>/`, from a new `state.models_dir(env=None, create=True)` beside `state_dir`. Data, not state: large, identical for every profile, kept outside the per-profile state directory and its sweeps. Never the working directory. `XDG_DATA_HOME` joins `.env.example`.

**(c) Sizes.** `tiny` (about 75 MB), `base` (about 150 MB), `small` (about 500 MB); default `base`. No `medium`, `large-*` (over a gigabyte and slow on a CPU inside a delivery loop) and no `.en` variants: an English-only model decodes Urdu as confident English, the exact failure the docs warn about, and the docs give that reason. `--model` (on `transcribe`) and `--transcribe-model` (on `recv`) take a size for `local`; anything else is `bad_usage` listing the three. The figures are the issue's and unmeasured: the tables say "about", and the post-merge step confirms them.

Also approved: `local_not_ready` (16, not retryable), one warning up front in `recv`, a failed download mapping to 13, `vad_filter=True`, language auto-detect with `--language` passed through, `--key-env` with `local` as `bad_usage`.

### Confirmed from the package source (faster-whisper 1.2.1)

Read from the wheel (`pip download faster-whisper --no-deps`, unpacked in a scratchpad; nothing installed, no model fetched, no service called):
- `faster_whisper.download_model(size_or_id, output_dir=None, local_files_only=False, cache_dir=None, revision=None, use_auth_token=None)` is exported at the top level; `output_dir` is passed to `huggingface_hub.snapshot_download` as `local_dir` with symlinks off, so a plain directory results. It fetches exactly `config.json`, `preprocessor_config.json`, `model.bin`, `tokenizer.json`, `vocabulary.*`. The size names `tiny`, `base`, `small` map to the `Systran/faster-whisper-<size>` repos; an unknown size raises `ValueError`.
- `WhisperModel(model_size_or_path, device="auto", device_index=0, compute_type="default", cpu_threads=0, num_workers=1, download_root=None, local_files_only=False, ...)`. **`os.path.isdir(path)` decides everything**: a directory is loaded as is; anything else is treated as a size or repo id and downloaded. So the recv path must check `is_ready` first and never hand it a path that might not exist. And **a directory with no `tokenizer.json` falls back to a tokenizer fetched from the network**, so `tokenizer.json` is part of the ready check, not just `model.bin` and `config.json`.
- `WhisperModel.transcribe(audio, language=None, ..., vad_filter=False, ...)` returns `(segments, info)` where `segments` is a **lazy generator** (it must be consumed inside the call that joins it), each with `.text`. `vad_filter` defaults to `False` here, so it is passed explicitly. The Silero VAD model ships inside the wheel (`assets/`): no download. Audio decoding is by PyAV (`av`), a dependency, so ogg/opus voice notes need no separate ffmpeg.
- Dependencies of the wheel: `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av`, `tqdm`. The extra is pinned `faster-whisper>=1.2,<2` because that is the version read; an older release was not checked.
- Not confirmed and left for the post-merge step: the real download, the real byte sizes, and behaviour of an actual model on an actual voice note.

## Success criteria

- [x] `pip install "wa-agent[local]"` is declared: `pyproject.toml` has a `local` extra containing `faster-whisper`, the README names the extra, and the existing extras check (declared and mentioned agree) passes — `verify: python3 tests/smoke.py`
- [x] The default install does not pull the local dependency: `[project] dependencies` names no `faster-whisper` and none of its known heavy dependencies, and in a fresh interpreter `import wa_agent, wa_agent.cli` leaves `faster_whisper` out of `sys.modules` — `verify: python3 tests/smoke.py`
- [x] Smoke passes without the extra installed: it never imports the real `faster_whisper`, fakes it completely for the local tests, and the section that proves "not installed" runs with `sys.modules["faster_whisper"] = None` — `verify: python3 tests/smoke.py`
- [x] `transcribe(path, provider="local")` with a faked engine returns the words as a plain `str`, without a key in the environment, without a session, and without any request made — `verify: python3 tests/smoke.py`
- [x] `local` is never chosen by absence: with no `GEMINI_API_KEY` and no `--provider`, `transcribe` still exits 12; with the extra installed and a model on disk, that is still so — `verify: python3 tests/smoke.py`
- [x] The model download is explicit and states its size first: `model pull tiny` prints the size line before the faked download starts, downloads into `<size>.partial` then renames, is a no-op naming the path when present, and exits `local_not_ready` when the extra is absent; a directory lacking `tokenizer.json` is not ready, and `run` never constructs a model for a directory that is not; a failed download leaves no ready-looking directory and exits 13 — `verify: python3 tests/smoke.py`
- [x] Nothing downloads during `recv`: with the extra faked and no model on disk, `recv --transcribe --provider local` warns once before its first poll, marks the voice note `transcribed: false` with `transcription_error: "local_not_ready"`, and the fake engine records zero download calls; the model is built from an existing local directory only — `verify: python3 tests/smoke.py`
- [x] A transcript carries its engine: a local `recv --json` voice note has `transcribed_by: "local:base"` (or the size given), `transcribe()` still returns a plain `str`, and the Gemini and OpenRouter `recv --json` lines are byte-identical to before (the existing sections pass with only the edits this ticket forced: the four assertions that used `local` as the unbuilt provider, the pinned `MODELS` line, and doctor's line count and indexes for its new line) — `verify: python3 tests/smoke.py`
- [x] An empty local result is `transcription_failed` (14), silence included (`vad_filter` is passed), and an engine that raises is 14 too, with the reason in `detail` and none in the fixed message — `verify: python3 tests/smoke.py`
- [x] `--key-env` with `--provider local` is `bad_usage`; an unknown size is `bad_usage` naming the offered sizes — `verify: python3 tests/smoke.py`
- [x] `state.models_dir` resolves `$XDG_DATA_HOME/wa-agent/models`, else `~/.local/share/wa-agent/models`, never the working directory, and doctor's look at it creates nothing — `verify: python3 tests/smoke.py`
- [x] Doctor has a `local engine` line that is never `FAIL`: `optional` when the extra is missing or no whole model is downloaded, `ok` naming the sizes when it could run; it makes no request, imports no engine, and writes nothing; every keyed provider still has a key probe, and `local` is the one provider without — `verify: python3 tests/smoke.py`
- [x] `docs/errors.md` has the `local_not_ready` row and a plain statement of what the local engine is bad at (Urdu, Roman Urdu, code-switching, background noise), and so does the README; the documented-codes check passes — `verify: python3 tests/smoke.py`
- [x] No OpenAI-server string anywhere: the existing scan (no `OPENAI_`, no `api.openai.com`, `openai` appears only in the `MODELS` constant) passes with the new module and docs included — `verify: python3 tests/smoke.py`
- [ ] **Post-merge, owner + lead:** with `pip install "wa-agent[local]"` and `wa-agent model pull` run for real, an English voice note transcribes offline with no key and the network off; the real download sizes are compared with the table and the results pasted into "Live confirmation" below — `verify: manual` (Phase 5; **this box stays unticked** until then)
- [x] Repo check passes — `verify: python3 tests/smoke.py`

## Phases

Every phase ends with `.venv/bin/python tests/smoke.py` (the system python3 has an older wa-agent). No live run, no network, no download at any point.

### Phase 1 — The engine and the library
**Status:** Done — `local.py` (sizes, ready check, `pull`, `run`), `state.models_dir`, `KEYED_PROVIDERS`/`PROVIDERS`, `check_usage`, the local branch of `transcribe()`, code `local_not_ready` (16) and its `docs/errors.md` row (moved here from Phase 4: smoke fails on an undocumented code); doctor's key loop now iterates `KEYED_PROVIDERS` (its `local` line is Phase 3); the four smoke assertions that used `local` as the unbuilt provider changed; new section `local transcription (library)`; smoke passes.
- Files: new `wa_agent/local.py`; `wa_agent/transcribe.py:22-32` (constants), `:62-77` (`key_env_for`, `model_for`, `check_provider`), `:84-130` (`transcribe`); `wa_agent/state.py` (`models_dir` beside `state_dir`, `:44-73`); `wa_agent/errors.py:21-23,52-54` (new code); `tests/smoke.py:886-889`, `:1025-1028`, `:1073-1075`.
- Change:
  - `local.py`: `SIZES = {"tiny": 75, "base": 150, "small": 500}` (approximate MB) and `DEFAULT_SIZE = "base"`; `check_size(size)` (bad_usage naming the sizes); `extra_installed()` (`importlib.util.find_spec("faster_whisper")`, catching `ValueError` and `ImportError` as not installed); `model_path(size, env)`; `is_ready(size, env)` (`model.bin`, `config.json`, `tokenizer.json`); `installed_sizes(env)` (names of directories under `models_dir` that pass it, never a `.partial`); `pull(size, env, out)` which requires the extra, prints the size line, downloads to `<size>.partial` via `faster_whisper.download_model(size, output_dir=<dir>.partial)` (confirmed above), then checks `is_ready` on the result before renaming, renames on success, and maps any download exception to `transcription_unavailable`; `run(path, size, language, env)` which raises `local_not_ready` (naming the fix) if the extra or model is missing, **checks `is_ready` before it constructs anything**, loads `WhisperModel(str(model_path), device="cpu", compute_type="int8")` once per size into a module-level cache, calls `transcribe(str(path), language=language, vad_filter=True)`, consumes the lazy segment generator while joining the texts, and returns the string.
  - `transcribe.py`: `KEYED_PROVIDERS = ("gemini", "openrouter")`, `PROVIDERS = KEYED_PROVIDERS + ("local",)`, `MODELS["local"] = local.DEFAULT_SIZE` (the `openai/whisper-1` line stays the only place `openai` appears). `key_env_for("local")` returns `None`. `check_provider`'s message loses "(offline transcription is issue #20)". `transcribe()`: after the file and audio-type guards, `if provider == "local":` reject a `key_env` (bad_usage), run `local.run`, and return through `_nonempty`, a plain `str`; the key and session code stays below it, untouched for the two keyed providers.
  - `state.models_dir(env=None, create=True)`.
  - `errors.py`: `"local_not_ready": Error(16, "the local transcription engine is not ready; the detail line says what to install or download", False)`, and the docstring list gains `16`.
  - Smoke: the three places that use `"local"` as the unbuilt provider switch to an unknown name (`"whisper"`); the `"#20" in detail` assertions go with them.
- Test: new section `local transcription (library)` with a `fake_faster_whisper()` context manager (a `types.ModuleType` with a real `__spec__`, a `WhisperModel` recording its constructor arguments and every call, a top-level `download_model` writing `model.bin`, `config.json` and `tokenizer.json` into `output_dir`, with the real signature); asserts the criteria for a faked run (the fake's `WhisperModel` is constructed with an existing directory and `transcribe` receives `vad_filter=True`), a directory without `tokenizer.json`, empty and silent results, the not-installed path (`sys.modules["faster_whisper"] = None`), the not-downloaded path, `--key-env` and bad-size `bad_usage`, and `models_dir` under a temp cwd and a temp `XDG_DATA_HOME`.

### Phase 2 — The command line
**Status:** Done — `model pull [SIZE]`; `--provider local` on `transcribe` and `recv` (usage refused before the first poll, one up-front not-ready warning, `transcribed_by: "local:<size>"` on a local transcript only, stderr caveat on `transcribe`); help strings; new section `local transcription (command line)`; smoke passes.
- Files: `wa_agent/cli.py:93-95` (help constants), `:152-154` (`_transcribe_command`), `:196-226` (`_transcribe_into`), `:272-281` (`_recv`'s up-front block), `:340-393` (parsers), `:398-420` (`main`); `wa_agent/text.py` untouched.
- Change:
  - `model` subcommand (`p_model`, one sub-subcommand `pull`, the same shape as `media`); `main` routes it; `pull` writes to stderr as specified in (b).
  - `_recv`: for `local`, the up-front block runs `local.check_ready(size)` (the same check `run` makes) and warns once (`warning: the local model "base" is not downloaded; voice notes will arrive untranscribed (wa-agent model pull base)`), instead of the key warning; unknown size or a `--key-env` refuses before the first poll, like `check_provider` does.
  - `_transcribe_into`: on success when `args.provider == "local"`, `message["transcribed_by"] = f"local:{size}"` from `args.provider` and the resolved `args.transcribe_model`, and the stderr line gains the tag; on a coded failure nothing changes (`transcribed: false`, `transcription_error: <code>`).
  - `_transcribe_command`: the one stderr note on the local path.
  - Help strings: `--provider` and `--model`/`--transcribe-model` say what `local` takes; the `#20` mention in `p_tr` goes; `KEY_ENV_HELP` says `--key-env` does not apply to `local`.
- Test: `recv --transcribe --provider local` end to end with a fake session (the voice note's download) and the fake engine: `transcribed_by` present, words in `text.body`, store records the words, audio not kept, one `transcribed <id>` stderr line; a Gemini and an OpenRouter `recv --json` line asserted to equal their previous bytes and to have no `transcribed_by`; the not-ready warning appears once and no download call is recorded; `model pull` output (size line first, then the fake download).

### Phase 3 — Doctor
**Status:** Done — `doctor.check_local` (a `local engine` line after the key lines; `optional` without the extra or without a whole model, `ok` naming the sizes on disk, never `FAIL`, no request, no import, nothing written); the existing doctor tests updated for the extra line; new local-engine tests and the parity rule; smoke passes.
- Files: `wa_agent/doctor.py:27` (import), `:134-153` (`check_key` beside which the new check sits), `:196-207` (`run_checks`); `tests/smoke.py:1493-1497` (the parity check) and the doctor tests that count or name lines.
- Change: `check_local(env=None)` returning `Check("local engine", OPTIONAL, ...)` in every state, three fixed messages naming the extra, `wa-agent model pull`, or the sizes present (by directory name) and the directory; `run_checks` iterates `KEYED_PROVIDERS` for keys and appends `check_local` after them; module docstring says the local line makes no request and imports nothing.
- Test: parity becomes `set(KEY_PROBES) == set(transcribe.KEYED_PROVIDERS)` and `set(transcribe.PROVIDERS) - set(KEY_PROBES) == {"local"}`; the three states, no request made, no file created under a temp `XDG_DATA_HOME`, exit `0` whatever the state; the existing doctor sections adjusted only for the added line.

### Phase 4 — Packaging and docs
**Status:** Done — `local = ["faster-whisper>=1.2,<2"]` extra; README (install, table rows, keeps-things, what the engine is bad at), `docs/errors.md` ("What no code can tell you"), `.env.example` (`XDG_DATA_HOME`); smoke proves the default install is one dependency and never imports the engine, and that the docs say plainly it is weak on Urdu and code-switching.
- Files: `pyproject.toml:26-30` (the comment and the extras), `README.md:39-49`, `:94`, `:97`, `docs/errors.md:24-40` and the intro, `.env.example`, `wa_agent/doctor.py` docstring if needed; `tests/smoke.py` (default-install proof).
- Change:
  - `pyproject.toml`: `local = ["faster-whisper>=1.2,<2"]` under the extras; the comment that says "Offline transcription will need one (#20)" is rewritten.
  - README: install section gains `pip install "wa-agent[local]"`, `wa-agent model pull`, `wa-agent transcribe note.ogg --provider local`, and a short "What the local engine is bad at" paragraph: fine for clear, accented English; poor at Urdu, Roman Urdu and speech that switches language; can produce fluent, confident, wrong text instead of failing; blocks the relay for the duration of each note; off unless you choose it. The `transcribe` and `doctor` table rows follow.
  - `docs/errors.md`: the `local_not_ready` row, and the same honesty sentence where transcription failure modes are described.
  - `.env.example`: `XDG_DATA_HOME`, and a comment that `--provider local` needs no key.
  - Smoke: the default-install proof (dependencies list, and a subprocess that imports the package and the CLI and asserts `faster_whisper` is not in `sys.modules`).
- Test: `python3 tests/smoke.py` passes; the README and `.env.example` checks (extras declared and mentioned, variables documented, commands exist in `--help`) pass.

### Phase 5 — Post-merge, on a real machine
**Status:** Not started — the owner and the lead run this after the PR merges. **Its box stays unticked** and I do not run it.
- `pip install "wa-agent[local]"`, `wa-agent model pull`, then `wa-agent transcribe <english note>.ogg --provider local` with the network off; `wa-agent doctor` shows the `local engine` line as ok. Compare the real download sizes with the table and paste the results into "Live confirmation".

### Live confirmation
_Pending Phase 5._

## Risks

- **The API is now read, not remembered** (see "Confirmed from the package source"), but only for 1.2.1, hence the pin. What stays unconfirmed is the real download and a real model on a real note, which is Phase 5.
- **Whisper on silence and on Urdu.** `vad_filter` reduces fabricated text on silence; nothing here detects a note in the wrong language. That is documented, not solved; a language-detection guard would be its own ticket.
- **Model load time and memory** inside a delivery loop: a load once per process, and a blocking transcription per note. Documented. `tiny` and `base` are the offered defaults for that reason.
- **The size figures are approximate** and stated as such until Phase 5.
- **A ready directory is trusted by file names.** A corrupt `model.bin` passes `is_ready` and fails inside the engine; that surfaces as `transcription_failed` (14) with the engine's message in `detail`, not a crash.

## Out of scope

- Automatic fallback to local when a key is missing (the issue forbids it).
- `medium`, `large-*` and `.en` models, `model list`, GPU or `compute_type` options, a model directory flag.
- Detecting or refusing a note in a language the model is bad at.
- The version and the CHANGELOG: #20 goes into a later release than 0.2.0.
- Any live run, WhatsApp, Gemini or OpenRouter call.
