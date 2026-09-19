---
type: ExecPlan
slug: GH-44-dotenv
issue: 44
status: completed
open_questions: none
---

# feat: Read ./.env in every command, and say where each variable came from          ✅ COMPLETED — 2026-09-20

## Problem
[#44](https://github.com/mhmzdev/whatsapp-agent-cli/issues/44). `wa-agent` reads only what the shell exported. A token sitting in `./.env` is invisible: `doctor` says "no token", and `send` and `recv` exit `no_token`. Only `make up` and `make live` load `.env` first, so anyone who runs the command directly trips over it.

The owner has settled the WHAT, and this plan does not reopen it. Every command reads `./.env` in the working directory, and nowhere else. The shell always wins. Names and sources go to stderr, values never do. There is no new dependency. The provider is still never inferred from which keys are present. This reverses the old rule that the CLI never loads `.env`. That rule is written in `.env.example:3-9`, `tests/live.py:8-9,33` and, less directly, in AGENTS.md's "Secrets only from the environment" (`AGENTS.md:64`).

## Approach

### The parser: a new `wa_agent/envfile.py`, used only by the CLI
The module is pure, uses only the standard library, and is not re-exported from `wa_agent/__init__.py`:

- `parse(text) -> (values: dict, skipped: list[int])`
  - A blank line, or one whose first non-space character is `#`, is ignored without a warning.
  - An optional leading `export ` is dropped.
  - The key must match `[A-Za-z_][A-Za-z0-9_]*`. Whitespace around the key and after `=` is allowed.
  - An unquoted value runs up to an inline comment (whitespace then `#`) and is stripped. `a#b` stays `a#b`.
  - A value in `'…'` or `"…"` is taken literally: no escapes, no `$` interpolation, and it cannot span lines. After the closing quote, only whitespace or a `# comment` may follow.
  - Anything else goes into `skipped` by its 1-based line number: no `=`, a bad key, an unclosed quote, or text after the closing quote. Examples are `NOT A LINE` and `KEY="abc`.
  - A key that appears twice takes its last value, as `source` would.
  - A key whose value is empty or blank contributes nothing. A `.env` copied from `.env.example` therefore supplies no variables.
- `load(directory) -> (values, skipped, problem)` reads `directory / ".env"` as `utf-8-sig`, so a BOM is dropped. If there is no file, the result is `({}, [], None)`. If the file cannot be read (`OSError`) or is not valid UTF-8, the result is `({}, [], "cannot be read")` or `({}, [], "is not UTF-8")`. The CLI turns that into one warning, and the command carries on with the shell alone.
- `merge(shell, values) -> (merged, sources)` returns a new `dict`. `os.environ` is never mutated. A variable counts as set in the shell only if its value is non-blank, which is the same test every reader in the package already applies (`(env.get(X) or "").strip()`, e.g. `state.py:28`, `transcribe.py:67`). A blank export therefore does not hide the `.env` value behind a run that then exits `no_token`. For every name set in either place, `sources[name]` is one of `SHELL`, `DOTENV`, or `SHADOWED`. `SHADOWED` means both set it and the shell's value was used.

### Where loading happens: the CLI only (proposal c, agreeing with the lead's steer)
`cli.main` already takes `env` and passes it to every path (`cli.py:434-462`), and `_fail` reads `WHATSAPP_AGENT_DEBUG` from it (`cli.py:498`). Loading goes into `main` after `parse_args`, so `--help`, `--version` and a usage error exit before any file is read, and their output does not change. The merged mapping replaces `env` for the rest of the run. Nothing in the library changes how it resolves anything. `import wa_agent`, `resolve_token()`, `transcribe()`, `run_checks()` and Hisab's adapter keep reading `os.environ` or the mapping they are given, and never a file in someone's working directory. Smoke proves this in a subprocess that runs from a temp directory holding a `.env`.

`main` gains a keyword `cwd=None`, a seam for the check in the same way `session` and `sleep` are. It is the directory `./.env` is looked for in, and defaults to `Path.cwd()`. `run_cli` in smoke passes an empty temp directory by default. The `-m wa_agent` subprocesses at `tests/smoke.py:1941,1946` switch from `cwd=ROOT` to an empty temp directory. With those two changes, no smoke run can read the repo's real `.env`.

All of `.env` goes into the mapping, not just the names we know. That lets `--key-env MY_KEY` find `MY_KEY` in `.env`, and it is harmless because the mapping never reaches `os.environ` or a child process.

### What is reported, and when (proposal a)
**Which names are reported:** the variables `.env.example` documents, which the check already treats as "every variable the code reads" (`tests/smoke.py:811`): `WHATSAPP_AGENT_TOKEN`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `XDG_STATE_HOME`, `XDG_DATA_HOME`, `WHATSAPP_AGENT_DEBUG`. The name given to `--key-env` is added when the subcommand has that option. A name is listed only when it is set somewhere. The list is the same for every subcommand. Filtering per subcommand would be a second table to keep in step, and it would hide a stray `.env` key exactly when someone is trying to work out why a run behaves as it does.

**When it prints:** only when `./.env` supplied or shadowed one of those names. Then it prints once per process, before the subcommand runs. With no `.env`, a `.env` that sets none of them, or `--no-env-file`, stderr stays byte-for-byte what it is today. A script that calls `send` a thousand times from a folder without a `.env` sees nothing new, and `recv --follow` prints its one line at start-up and never again.

**Format:** one line, fixed text plus names, using the `word:` prefix convention of the existing stderr lines (`note:`, `warning:`, `error [code]:`):

```
env: WHATSAPP_AGENT_TOKEN from ./.env; GEMINI_API_KEY from the shell (./.env also sets it, not used)
```

Names appear in the order of the list above, separated by `; `. The separator is ASCII, so a C-locale terminal or a log file shows it plainly. A skipped line produces its own warning, once per run and even when nothing else prints:

```
warning: ./.env line 7 is not KEY=VALUE; skipped
warning: ./.env cannot be read; ignored
```

The warning gives the line number and never the line. Every string here is a constant plus a name from the list. No value, no path beyond `./.env`, and no exception text reaches it.

### The opt-out (proposal b)
The opt-out is a global flag, `--no-env-file`, placed before the subcommand like `--token-file`. With it, `main` neither opens nor stats `./.env`, prints nothing, and passes `env` through unchanged, so the run is the old behaviour exactly. There is no environment variable for it. A switch that lives in the environment could itself be set by `.env`, which is circular, or it would need its own "shell only" exception, and it would be a seventh variable to document. Every caller that wants the old behaviour controls its own argv: a script, a cron line, or a systemd `ExecStart=`. The library never needs it, because the library never reads the file.

### `--token-file` against a token from `./.env` (proposal e, found while planning)
Today `$WHATSAPP_AGENT_TOKEN` beats `--token-file` (`state.py:20-44`). The reason was that a systemd unit or a CI secret should not have to be written to disk. That reason does not apply to a token read from a file in the working directory. Left alone, a `.env` the user forgot about would quietly override a `--token-file` they typed. The proposal: **the shell, then `--token-file`, then `./.env`.** When `--token-file` is given and the token came only from `.env`, `main` drops it from the merged mapping and reports `WHATSAPP_AGENT_TOKEN from ./.env, not used (--token-file given)`. A token exported in the shell still beats `--token-file`, exactly as it does today.

### Doctor (proposal d)
`run_checks` gains `sources=None`, a mapping from name to source that the CLI passes and the library omits. Without it, lines read as they do today. Every line whose answer depends on a variable names the variable and where it came from:

| Line | Example |
|---|---|
| token | `accepted by the platform (WHATSAPP_AGENT_TOKEN from ./.env)` · `(WHATSAPP_AGENT_TOKEN from the shell; ./.env also sets it, not used)` · `(--token-file ~/.wa-token)` |
| token, none | `no token in WHATSAPP_AGENT_TOKEN (the shell or ./.env) and no --token-file`; fix: `export WHATSAPP_AGENT_TOKEN, put it in ./.env, or pass --token-file PATH before the subcommand` |
| key | `GEMINI_API_KEY from ./.env, accepted by Gemini` · `GEMINI_API_KEY is not set in the shell or ./.env; only needed for --provider gemini` |
| local engine / state dir | the existing message, plus `(XDG_DATA_HOME from ./.env)` or `(XDG_STATE_HOME from ./.env)` only when that variable is set |
| python, creator | unchanged: no variable decides them |

With `--no-env-file`, the CLI passes `sources=None`, so the report is exactly the old one, word for word, the same as a library caller's. (This replaces an earlier draft that added `(./.env not read: --no-env-file)`: that would have broken "the opt-out restores the old behaviour exactly".) The one `env:` stderr line prints for doctor as for any command, which satisfies the issue's "stderr says" for doctor too. Doctor still makes no new request: the file is read before the checks run, and it is never written.

### Invariants kept
Transport is untouched: dedup, offset after the batch, dead-token exit, chunking. `recv --json` stdout is unchanged, because every new line goes to stderr. The provider still comes only from `--provider`: `.env` adds keys to the mapping, and `transcribe.check_usage`, `key_env_for` and `model_for` are not touched. State and models still never come from the working directory, unless the user deliberately puts `XDG_STATE_HOME` in `.env`. No value is printed anywhere. No dependency is added.

### Docs
- **README:** the "Secrets come from the environment" row (`README.md:76`) becomes "…from the environment, or ./.env". "Get a token" (`:94`) gains the `.env` alternative. The global-options sentence (`:139`) lists `--no-env-file`. One short paragraph under Get a token covers the shell winning, the `env:` line and the opt-out.
- **`.env.example`:** the header (`:3-9`) is rewritten to say that `wa-agent` reads `./.env` from the directory it runs in, that the shell wins, and that `--no-env-file` turns it off. The token comment (`:14-17`) gains the `--token-file` precedence.
- **`docs/errors.md`:** the `no_token` row (`:27`) becomes "the shell or ./.env", with the fix "put it in ./.env". `errors.py:12,44` gets the same wording.
- **AGENTS.md:** the non-negotiable at `:64` becomes "Secrets only from the environment, `./.env` in the working directory (read by the CLI only, never by the library; the shell wins), or a token file outside the repo…". The repo map gains an `envfile.py` line, and the `state.py` line (`:37`) gets the new token order.
- **`tests/live.py:8-9,33`:** these lines stop saying the CLI deliberately ignores `.env`. The script's own loader stays, because it decides what the script can test.
- **`Makefile:52`:** `make up` drops `set -a; . ./.env; set +a`. The CLI now reads `.env` itself, and exporting it first would make every variable read as "from the shell (./.env also sets it)".
- The docstrings for `state.py:1-8` (the library never reads `.env`) and `transcribe.py:17-19` (the key comes from the environment, which the CLI can fill from `./.env`) are updated.

## Success criteria
- [x] With `WHATSAPP_AGENT_TOKEN` only in `./.env`, `doctor`, `send --dry-run` and `recv` (fake session) all exit 0, and stderr has `env: WHATSAPP_AGENT_TOKEN from ./.env`. The fake session's `Authorization` header on `recv` and on a real `send` is the `.env` sentinel. Doctor's token line says `WHATSAPP_AGENT_TOKEN from ./.env` — `verify: python3 tests/smoke.py`
- [x] With the token in both the shell and `./.env`, the shell's sentinel is in the header, and stderr says `from the shell (./.env also sets it, not used)`. A blank shell export does not shadow `.env` — `verify: python3 tests/smoke.py`
- [x] No sentinel value, and no text from a skipped line, appears on stdout or stderr in any `.env` scenario, with `WHATSAPP_AGENT_DEBUG=1` set from the shell and from `.env`, including a run that fails `auth` and prints a traceback — `verify: python3 tests/smoke.py`
- [x] `recv --json` stdout is byte-identical between the token in the shell and the token in `./.env`, for the same fake batch. The `env:` line is on stderr only — `verify: python3 tests/smoke.py`
- [x] `--no-env-file` with a `.env` holding a sentinel token gives exactly the exit status, stdout and stderr of the same run in a directory with no `.env` (`send` exits 3 `no_token`; `doctor` exits 15, and its report is word for word what the library renders). A run with no `.env` at all prints no `env:` line — `verify: python3 tests/smoke.py`
- [x] The parser table: comments, blanks, `export `, both quote styles, inline `#`, a BOM, CRLF, a duplicate key, an empty value, and each malformed shape skipped by line number. An unreadable `.env` (a directory named `.env`) warns and the command carries on — `verify: python3 tests/smoke.py`
- [x] The library never reads `./.env`: a subprocess started in a temp directory whose `.env` holds a token, with no token in its environment, gets `no_token` from `resolve_token()`. Importing `wa_agent` there opens no `.env` — `verify: python3 tests/smoke.py`
- [x] The provider is not inferred: with only `OPENROUTER_API_KEY` in `./.env`, `transcribe` with no `--provider` still exits 12 `no_transcription_key` naming `GEMINI_API_KEY` — `verify: python3 tests/smoke.py`
- [x] `--token-file` beats a token that only `./.env` supplies, and the `env:` line says `not used (--token-file given)`. A shell token still beats `--token-file` — `verify: python3 tests/smoke.py`
- [x] README, `.env.example`, `docs/errors.md` and AGENTS.md say `./.env` is read, the shell wins, and `--no-env-file` exists. The `.env.example` smoke assertion is updated from "source .env" to those facts. The CHANGELOG and the version are untouched — `verify: python3 tests/smoke.py && git diff --quiet origin/develop -- CHANGELOG.md pyproject.toml wa_agent/__init__.py`
- [x] Repo check passes — `verify: python3 tests/smoke.py` (in the editable `.venv`)

## Phases

### Phase 1 — The parser and the CLI merge
**Status:** Done — `wa_agent/envfile.py` (parse/load/merge); `cli.main` reads ./.env after argparse unless `--no-env-file`, fills gaps (a blank export is a gap), puts `--token-file` ahead of a `.env`-only token, prints the `env:` line only when ./.env mattered and a numbered warning per skipped line; smoke's `run_cli` and `-m wa_agent` runs look in an empty directory; new `./.env` section.
- Files: new `wa_agent/envfile.py`; `wa_agent/cli.py:353-362` (the `--no-env-file` global option and the epilog), `:434-462` (`main`: `cwd=`, load after `parse_args`, merge, token-file precedence, warnings, the `env:` line); `tests/smoke.py:62-73` (`run_cli` gains `cwd=`, defaulting to an empty temp dir), `:1941,1946` (subprocess cwd).
- Change: implement `parse`/`load`/`merge` as above. In `main`, the order is: `env = os.environ if env is None else env`, parse the arguments, then run `_load_env_file(args, env, cwd)` unless `args.no_env_file`. That helper returns the merged mapping and the sources, prints the warnings and the `env:` line to stderr, and drops a `.env`-only token when `args.token_file` is set. The reported names come from the constant `REPORTED` in `cli.py`, plus `getattr(args, "key_env", None)`. `sources` is stashed for `_doctor` to pass on. The dispatch is otherwise unchanged.
- Test: a new `section(".env")` in smoke, placed before "doctor", covering the parser table, merge and shadowing, blank-shell handling, the `env:` line's exact text and when it appears, `send --dry-run`, `send` and `recv` with a fake session (header checks), `recv --json` byte-identity, `--no-env-file` equivalence, token-file precedence, provider not inferred, the sentinel sweep with debug from both sources and a failing `auth` run, and the library subprocess from a temp cwd.

### Phase 2 — Doctor shows the source
**Status:** Done — `envfile.describe` is the one phrasing, shared by the `env:` line and doctor; token, keys, state dir and local engine say where their variable came from, and "none" names ./.env; `--no-env-file` and library callers get the old report word for word; the smoke doctor section gains scenario 8.
- Files: `wa_agent/doctor.py:97-136` (`_token_source`, `check_token`), `:139-158` (`check_key`), `:161-171` (`check_local`), `:181-198` (`check_state_dir`), `:214-226` (`run_checks(sources=None)`); `wa_agent/cli.py:464-474` (`_doctor` passes `sources` and whether `.env` was read).
- Change: add a helper `_from(name, sources)` that returns `"from ./.env"`, `"from the shell"` or `"from the shell; ./.env also sets it, not used"`, or `""` when `sources` is None, so library callers see today's text. Rewrite the messages as in the table above. Line order, statuses and the no-poll, no-write rules are unchanged.
- Test: extend the doctor section. Add the token from `./.env`, the token shadowed, a key from `./.env`, `XDG_STATE_HOME` from `./.env`, and the none-anywhere wording with and without `--no-env-file`. `run_doctor`'s existing secret sweep and no-poll invariants apply to every new case. Update existing assertions only where the wording deliberately changed (`"--token-file" in …` and `"WHATSAPP_AGENT_TOKEN" in fixes[1]` still hold).

### Phase 3 — Docs and the reversed rule
**Status:** Done — README (secrets row, a `.env` paragraph under Get a token with the Hisab sentence, `--no-env-file` among the globals), `.env.example` header, `docs/errors.md` and `errors.py` `no_token`, AGENTS.md non-negotiable and repo map, `state.py`/`transcribe.py` docstrings. `make up` no longer exports `.env` itself, and `tests/live.py` no longer exports it into the CLI's environment: both run the CLI from the repo root so it reads `./.env` itself and the `env:` line is honest. live.py uses `envfile` only to decide what it can test.
- Files: `README.md:76,94,139` plus a paragraph under Get a token; `.env.example:1-17`; `docs/errors.md:27`; `wa_agent/errors.py:12,44`; `AGENTS.md:37,64` and the repo map; `tests/live.py:8-9,33`; `Makefile:52`; the docstrings at `wa_agent/state.py:1-8` and `wa_agent/transcribe.py:17-19`; `tests/smoke.py:813` (the `.env.example` assertion).
- Change: as listed under Approach → Docs. No CHANGELOG entry, no version bump.
- Test: the smoke README and `.env.example` checks assert that `--no-env-file` appears in both and in `wa-agent --help`, that `.env.example` says the shell wins, and that `.env.example` still carries no value.

## Risks
- **A hostile `.env` in a cloned repo.** Running `wa-agent` inside someone else's checkout lets their `.env` fill gaps: a token for their agent, or an `XDG_STATE_HOME`. The shell wins, and the `env:` line names every variable `.env` supplied before the command acts, so it is visible, not silent. The owner accepted this with "every command reads ./.env". It is recorded here, not reopened.
- **Smoke reading the owner's real `.env`.** `run_cli` is in-process and its cwd is wherever smoke runs. This is closed by `cwd=` defaulting to an empty temp dir and by moving the two `-m wa_agent` subprocesses off `ROOT`. The implementer must never read, print or copy the real `.env`.
- **Doctor wording.** The wording changes may break exact-match assertions elsewhere in smoke. Phase 2 updates only those that the change deliberately touches.
- **A parser that disagrees with the shell** on an edge case, such as escapes in double quotes. That behaviour is documented as literal. A token or key has no escapes, and the "whitespace inside" checks in doctor still catch a pasted line break.

## Out of scope
- Walking up parent directories, a home-directory file, or a `--env-file PATH` flag. The owner decided on `./.env` only.
- Loading `.env` in the library, or exporting it into `os.environ` or a child process.
- An environment variable that turns off `.env` loading (see proposal b).
- Variable interpolation, multi-line values and escape sequences.
- A CHANGELOG entry and a version bump, which wait for the release PR.
