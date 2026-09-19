# Changelog

Versions follow [SemVer](https://semver.org). Before `1.0.0` the API may still move; `1.0.0` comes once Hisab runs on this package and nothing had to change.

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
