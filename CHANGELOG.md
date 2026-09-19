# Changelog

Versions follow [SemVer](https://semver.org). Before `1.0.0` the API may still move; `1.0.0` comes once Hisab runs on this package and nothing had to change.

## 0.3.0 — offline transcription

**Transcription, offline**
- `--provider local` transcribes on this machine with Whisper, through the opt-in extra: `pip install "wa-agent[local]"`. No key and no network once a model is downloaded. The default install does not pull it.
- `wa-agent model pull [tiny|base|small]` is the only thing that ever downloads a model. It states the size first (`base`, the default, is about 150 MB), writes to a partial directory and renames only once every file is there. Models live under `$XDG_DATA_HOME/wa-agent/models` (else `~/.local/share/wa-agent/models`), shared across profiles, never in the working directory.
- Nothing downloads during `recv`. `recv --transcribe --provider local` before `model pull` warns once, naming the fix, and delivers voice notes marked `transcribed: false`.
- `recv --json` adds `"transcribed_by": "local:<size>"` to a locally transcribed note, and nothing to a Gemini or OpenRouter one.
- **It is weak on Urdu and on mixed-language speech.** Whisper's small models turn those into confident, fluent, wrong English. It is never chosen for you: `local` is used only when you ask for it, never because a key is missing. English-only (`.en`) models are not offered for the same reason.

**Doctor**
- A new `local engine` line says whether the extra is installed and which models are downloaded. It makes no request and writes nothing.

**Changed**
- New exit code `16`, `local_not_ready`: the extra is not installed or the model is not downloaded. Not retryable. The line names the fix.
- `PROVIDERS` now includes `local`. Library code that loops over `PROVIDERS` expecting a key for each should use the new `KEYED_PROVIDERS`.
- `--key-env` with `--provider local` is refused as `bad_usage`: the local engine has no key.

**Docs**
- The README says what the package does differently, a table of guarantees each pinned by the check, and gives transcription its own section comparing the three providers.

## 0.2.0 — OpenRouter transcription, and `doctor`

**Transcription**
- OpenRouter is a second provider beside Gemini: `wa-agent transcribe <file> --provider openrouter` and `recv --transcribe --provider openrouter`, reading `OPENROUTER_API_KEY`; `--model` takes an OpenRouter model id. From Python, `transcribe(path, provider="openrouter")`.
- The provider is always your choice — `gemini` unless you say otherwise — and never worked out from which key happens to be set.
- `recv --transcribe` refuses an unknown provider before its first poll, instead of marking every voice note failed.

**Doctor**
- `wa-agent doctor` checks a setup in one go, a line each: Python, the token, each transcription key, the state directory and the recorded creator, with the fix under anything that fails. Exits `15` (`doctor_failed`, new) when a check fails.
- It never polls, so it is safe beside a running `recv`, and it writes nothing. It does make real, free metadata requests to the platform and to every provider whose key is set.
- `WhatsApp.probe_token()` is new in the library: one read that says whether the platform accepts a token.

**Changed**
- `no_transcription_key` (exit `12`, unchanged) no longer names `GEMINI_API_KEY` in its message; its `detail:` line names the variable actually read.
- `transcribe()`'s `key_env` now defaults to `None`, meaning the chosen provider's own variable. A caller that passes nothing reads `GEMINI_API_KEY` exactly as before.

## 0.1.0 — first release

The WhatsApp Agent Platform transport, as a library and a command.

**Send**
- `wa-agent send` splits a long message on paragraph boundaries, numbers the parts `(i/n)`, and converts markdown to WhatsApp formatting. `--dry-run` shows exactly what would go out, with no token.
- `send --file` uploads and attaches in one step; `send --media` reuses an upload. Photos go as images, everything else as a document that keeps its filename.
- A long send that fails halfway reports every part that already arrived, so a retry duplicates nothing.

**Receive**
- `wa-agent recv` long-polls with a cursor that is saved only after a batch is delivered, and skips any message it has already seen — a crash repeats a message rather than losing one.
- `--follow` streams, backing off from 1s to 60s when the platform is unreachable and stopping on a dead token instead of spinning.
- `--transcribe` adds the words to a voice note (Gemini, `GEMINI_API_KEY`) without changing the message's shape; `--download` keeps photos and files as they arrive.
- The first message received records who you are, after which `send` needs no `--to`.

**Media and transcription**
- `wa-agent media get` / `media put` with per-type size caps checked before any upload, and downloads swept after a day.
- `wa-agent transcribe <file>` for any audio file. No extra install: it is an ordinary HTTPS call.

**Failures**
- Every failure prints `error [<code>]: …` and exits with a documented status; `wa-agent errors` lists them and [`docs/errors.md`](docs/errors.md) says what to do about each. Exit `7` and `13` are worth retrying; the rest are not.

**Library**
- `from wa_agent import WhatsApp, Store` — the same transport the command uses, with `requests` as the only dependency.
