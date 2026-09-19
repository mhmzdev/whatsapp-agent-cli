---
type: FeatChecklist
slug: GH-44-dotenv
issue: 44
timestamp: 2026-09-20T00:00:00Z
---

# GH-44-dotenv — acceptance checklist   (13 proven · 3 manual · 0 failing)

- [x] `WHATSAPP_AGENT_TOKEN` only in `./.env`: `doctor`, `send --dry-run` and `recv` all see it, and stderr says it came from `./.env`. Proven by `python3 tests/smoke.py`:
  - the `./.env` section: `send --dry-run`, `send` and `recv --json` with a fake session carry the `.env` sentinel in `Authorization`, and stderr is exactly `env: WHATSAPP_AGENT_TOKEN from ./.env`
  - doctor scenario 8: the token line reads `accepted by the platform (WHATSAPP_AGENT_TOKEN from ./.env)`
- [x] The same variable in the shell and in `.env`: the shell's value is the one sent, and stderr says `from the shell (./.env also sets it, not used)`. Doctor says the same with `;` so the parentheses do not nest. A blank shell export is a gap that `.env` fills.
- [x] No value ever reaches stdout or stderr, with or without `WHATSAPP_AGENT_DEBUG=1`. Every `.env` scenario sweeps six sentinels, one of which sits in a line that cannot be parsed. Debug is tested set from the shell and set from `./.env`, on `recv` and `send` runs that fail `auth` and print a traceback. Two mutations turn the check red: the value appended to the `env:` line, and the skipped line echoed in its warning.
- [x] `recv --json` stdout is byte-for-byte unchanged. The same fake batch gives identical stdout with the token in the shell (no `.env`) and with the token in `./.env`. The `env:` line is on stderr only.
- [x] The opt-out restores the old behaviour exactly:
  - with a `.env` holding a sentinel token, debug and a bad line, `--no-env-file` gives the same `(status, stdout, stderr)` as a run in an empty directory, for `send`, `recv --json` and `send --dry-run`
  - doctor under `--no-env-file` is word for word what `doctor.render(run_checks(...))` gives a library caller
  - a mutation where `--no-env-file` still reads the file turns the check red
- [x] With no `.env`, or one that sets nothing reported (unrelated keys, comments, blank values), stderr is exactly what it was, so there is no new line for scripts and `recv --follow` stays quiet.
- [x] The token order is the shell, then `--token-file`, then `./.env`. `--token-file` beats a `.env`-only token and the line says `not used (--token-file given)`. A token exported in the shell still beats `--token-file`.
- [x] The provider is never inferred. With only `OPENROUTER_API_KEY` in `./.env`, `transcribe` exits 12 naming `GEMINI_API_KEY` and makes no request. A `--key-env` name is found in `./.env` and reported.
- [x] The parser covers:
  - comments, blank lines, `export `, both quote styles taken literally, inline `#` only after whitespace, CRLF, a BOM (through `load`), and a duplicate or later-blank key
  - six malformed shapes, skipped by line number only
  - a file that is not UTF-8, and a `.env` that is a directory: each warns once and the command carries on
  - `.env.example` parses to nothing
- [x] The library never reads `./.env`. A subprocess in a temp directory whose `.env` holds a token imports `wa_agent`, `cli`, `envfile` and `doctor` under an audit hook: no `.env` is opened, and `resolve_token()` raises `no_token`. `os.environ` is unchanged after the whole section.
- [x] The check can never read the repository's own `.env`. `run_cli` defaults `cwd=` to an empty temp directory, and the two `python -m wa_agent` subprocesses run there too.
- [x] The docs are updated:
  - README: the secrets row, a paragraph under Get a token that includes the Hisab sentence, and `--no-env-file` among the global options
  - `.env.example`: the header and the token order
  - `docs/errors.md` and `errors.py`: `no_token`
  - AGENTS.md: the non-negotiable and the repo map
  - the smoke assertions now check for `--no-env-file`, "always wins", and `./.env` in the README
  - the CHANGELOG, `pyproject.toml` and `__init__.py` are untouched: `git diff --quiet origin/develop -- …` passes
- [x] The repo check passes: `python3 tests/smoke.py` in the editable `.venv`, under `env -i`, 31 sections, "all checks passed". The four mutations (`.env` beating the shell, a value in the `env:` line, `--no-env-file` still reading, a skipped line echoed) each turn it red.
- [?] **`make live`, first real run after the merge (owner).** `tests/live.py` has only been compiled. Run `make live ARGS="--send-only"` from the repository with the token only in `.env`:
  - each CLI step's stderr shows `env: WHATSAPP_AGENT_TOKEN from ./.env`
  - the script prints `.env sets: WHATSAPP_AGENT_TOKEN…`
  - the message arrives
- [?] **`make up` (owner).** With the token only in `.env`, `make up` starts, its first stderr line is `env: WHATSAPP_AGENT_TOKEN from ./.env`, and a text you send lands.
- [?] **`doctor` with a token from `./.env`, live (owner).** In a folder whose `.env` holds the demo token, run `env -i HOME=$HOME PATH=$PATH wa-agent doctor`. The token line reads `accepted by the platform (WHATSAPP_AGENT_TOKEN from ./.env)`, and no value appears anywhere.

## Conventions

- **Transport:** untouched. There is no change to dedup, the cursor, backoff, the 409 exit, the dead-token exit or chunking. `.env` is read once per process, before the first poll.
- **Secrets:** they now come from the environment, from `./.env` (CLI only), or from a token file. Every new message is fixed text plus a variable name. No value, no file line and no exception text is printed, and every scenario asserts it.
- **Read-only default / write boundary / session control:** not touched. This is transport only, and the relay does not exist yet.
- **Privacy:** the staged diff was scanned. The only external name is Hisab, which is public and already in the README. There are no paths, ids or tokens from a personal setup, and the test sentinels are made up.
- **Docs:** README, `.env.example`, `docs/errors.md` and AGENTS.md agree with `--help` (the epilog gives the token order).

## Findings

None at Critical or Important. The lead approved two deviations from the plan, and both are recorded in it:
- under `--no-env-file`, doctor gives the old report word for word
- the fix line for a key with whitespace in it names `./.env` when the key came from there

## Notes

- Once, during implementation, before the `cwd=` seam existed, an in-process smoke run read the repository's real `.env`. Only variable names reached stderr, no values, and no network call was possible: the earlier runs were `--version`, `--help` and usage errors, and the failing one used the canned `FakeSession`. The seam closes this for every run.
