---
type: ExecPlan
slug: GH-2-package-skeleton
issue: 2
status: completed
open_questions: none
---

# feat: package skeleton, state resolution and the smoke check          ✅ COMPLETED — 2026-09-17

## Problem

The repo has CI, a board and a spec, and no package. [#2](https://github.com/mhmzdev/whatsapp-agent-cli/issues/2) is the tracer bullet that makes `pip install -e .` produce a working `whatsapp-agent` command: it resolves its token and its state directory, prints its version, lists the subcommands the rest of the epic fills in, and brings the repo's check into existence so every later ticket has something to extend. Everything in epic [#1](https://github.com/mhmzdev/whatsapp-agent-cli/issues/1) is blocked on it. Spec: [`001-transport-cli`](../../specs/001-transport-cli.md).

## Approach

A flat package, `whatsapp_agent/`, built by hatchling, with `requests` as the only runtime dependency (hisab has run on `requests>=2.32` in production; nothing here needs async). The CLI is argparse from the standard library — a transport library that drags click or typer into every dependent's environment is a worse library, and the subcommand surface is small enough that argparse costs nothing.

Three ideas carry over from hisab, adapted rather than copied:

- **Typed failures, not tracebacks** — `hisab/errors.py:40` raises `HisabError(code, detail)` and `hisab/errors.py:50` classifies anything unforeseen. Here the same shape ends at an **exit code** instead of a WhatsApp reply, because our caller is a shell or another program. The library raises; the CLI catches, prints one line to stderr and exits with the code.
- **The dead-token distinction** — `hisab/wa.py:30` singles out a 401, or a 400 with `error.code` 100, as permanent. That distinction is a transport fact, so it belongs in this package's error table from the first commit, even though nothing polls yet.
- **The check as a linear script** — `tests/smoke.py` in hisab is a plain script of sections that print what they proved and assert. No pytest, no fixtures, no network. Same here, so the CI job stays `python3 tests/smoke.py`.

State resolution is this ticket's only real design decision, and the spec settles it: token from `WHATSAPP_AGENT_TOKEN`, else `--token-file`; state under `$XDG_STATE_HOME/whatsapp-agent/<profile>/` (falling back to `~/.local/state`), `--state-dir` overriding, profile defaulting to `default`. The rule the check enforces: **nothing is ever written into the caller's working directory.**

Subcommands land as stubs that exist in `--help` and exit with a distinct "not implemented" code. A stub that exits 0 would let a later ticket's absence look like success.

## Success criteria

- [x] `pip install -e .` then `whatsapp-agent --version` prints the version — `verify: pip install -e . && whatsapp-agent --version`
- [x] `whatsapp-agent --help` lists `send`, `recv`, `media`, `transcribe` — `verify: whatsapp-agent --help | grep -E 'send|recv|media|transcribe'`
- [x] `pyproject.toml` names the distribution `whatsapp-agent` at version `0.1.0` — `verify: python3 -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'))['project'];assert d['name']=='whatsapp-agent' and d['version']=='0.1.0'"`
- [x] Token resolution is env first, then `--token-file`; a missing token exits non-zero with one line and no traceback — `verify: python3 tests/smoke.py`
- [x] The state directory is created on first use and never inside the caller's working directory — `verify: python3 tests/smoke.py`
- [x] `tests/smoke.py` runs with no network and no token, and `check:` in `AGENTS.md` names it — `verify: python3 tests/smoke.py`
- [x] The "no check yet" fallback is gone from `.github/workflows/tests.yml` — `verify: grep -c 'does not exist yet' .github/workflows/tests.yml` prints `0`
- [x] The built wheel installs in a clean venv and runs — `verify: python3 -m build && python3 -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl && /tmp/v/bin/whatsapp-agent --version`

## Phases

### Phase 1 — Packaging and version
**Status:** Done
- Files: `pyproject.toml` (new), `whatsapp_agent/__init__.py` (new)
- Change: hatchling build backend; `[project]` with `name = "whatsapp-agent"`, `version = "0.1.0"`, `requires-python = ">=3.10"`, `dependencies = ["requests>=2.32"]`, `[project.optional-dependencies]` with `transcribe = ["google-genai>=1.0"]` and `dev = ["build", "twine"]`, `[project.scripts] whatsapp-agent = "whatsapp_agent.cli:main"`, and the URLs pointing at the repo. `__init__.py` exposes `__version__` via `importlib.metadata.version("whatsapp-agent")`, falling back to `"0.0.0+dev"` when the package is not installed, so importing from a source checkout never raises.
- Test: none yet — Phase 4 asserts the version resolves and matches `pyproject.toml`.

### Phase 2 — Errors and exit codes
**Status:** Done
- Files: `whatsapp_agent/errors.py` (new)
- Change: `WhatsAppError(code, detail)` carrying a code from a `CODES` table that maps each to an exit status and a one-line message; `AuthError` as the permanent-failure subclass (401, or 400 with `error.code` 100), mirroring `hisab/wa.py:30`; `classify(exc, default="internal")` in the shape of `hisab/errors.py:50`, so an unforeseen exception still exits with a sensible code rather than a traceback. Codes this ticket needs: `no_token`, `bad_usage`, `not_implemented`, `internal`. Exit statuses are unique and documented in the module docstring, because a shell caller branches on them.
- Test: Phase 4 asserts every code has a unique exit status and a message, that `classify` never returns an unregistered code, and that no message contains `Traceback` or an HTTP body.

### Phase 3 — Token, state and the CLI surface
**Status:** Done
- Files: `whatsapp_agent/state.py` (new), `whatsapp_agent/cli.py` (new)
- Change: `resolve_token(args, env)` — `WHATSAPP_AGENT_TOKEN` first, then `--token-file` read and stripped, else raise `WhatsAppError("no_token")`; the token is never logged or echoed. `state_dir(profile, override)` — `--state-dir`, else `$XDG_STATE_HOME/whatsapp-agent/<profile>`, else `~/.local/state/whatsapp-agent/<profile>`; created with `parents=True, exist_ok=True`, mode `0o700`; returns an absolute path and raises if it would land inside the current working directory. `cli.py` builds the argparse tree — global `--token-file`, `--state-dir`, `--profile`, `--version`; subcommands `send`, `recv`, `media get|put`, `transcribe`, each parsing its arguments and exiting with `not_implemented`. `main()` catches `WhatsAppError`, prints `error: <message>` to stderr and exits with its status.
- Test: Phase 4 covers resolution order, the working-directory rule, directory permissions, and `--help` listing every subcommand.

### Phase 4 — The check, and CI becomes enforcing
**Status:** Done
- Files: `tests/smoke.py` (new), `.github/workflows/tests.yml` (drop the fallback branch), `AGENTS.md` (`check:` and the Commands row lose "does not exist yet")
- Change: a linear script in hisab's style, sections printing what they proved: version resolution matches `pyproject.toml`; the error table is complete and its exit statuses unique; `classify` falls back to `internal`; no error message leaks a traceback or an HTTP body; token resolution order, including the missing-token exit; state directory creation, permissions and the working-directory rule (run under a `tempfile.TemporaryDirectory` as cwd); `--help` lists every subcommand; every stub exits with `not_implemented`, never 0. No network, no token, no writes outside a temp dir. Then remove the `else` branch in the workflow's "Repo check" step so a missing check fails CI instead of warning.
- Test: the script is the test; `python3 tests/smoke.py` exits 0 and prints a line per section.

## Risks

- **A stub that looks finished.** Mitigated by the distinct `not_implemented` exit code and the check asserting it, so `recv` cannot quietly "pass" before #5 lands.
- **The `0.0.0+dev` fallback hiding a broken install.** It only triggers outside an installed package; Phase 4 asserts the installed version matches `pyproject.toml`, and `release.yml` already installs the wheel in a clean venv before publishing.
- **Scope creep into #4/#5.** No HTTP call belongs in this ticket. The moment a `requests` import appears outside the dependency list, the ticket has grown.

## Out of scope

- Any actual platform call: `send`, `recv`, `media` and `transcribe` are stubs here.
- The message store (#5 needs it first), rate limiting, chunking, media handling.
- README rewriting — that is #3.
- Publishing — that is #8, and it is the epic's gate.

## What actually happened (2026-09-17)

Four phases as written, with two deliberate departures from the plan, both narrower than what the plan said:

1. **The state directory does not raise when it resolves inside the current working directory.** The plan asked for that guard; implementing it literally breaks the ordinary case of running from your home directory, since `~/.local/state` *is* inside `~`. The real requirement is that the default location is never *derived* from the working directory, which is what `state_dir` does and what the check proves by resolving from a temporary cwd with a temporary `HOME`. An explicit `--state-dir` inside the working directory stays the caller's business.
2. **`auth` joined the code table in Phase 2.** The plan listed four codes and also asked for `AuthError`; the subclass needs a code, so there are five. It carries no behaviour yet beyond its exit status — the poll loop in #5 is what raises it.

Additions the plan did not name: `whatsapp_agent/__main__.py`, so `python -m whatsapp_agent` is the same entry point as the installed command (the check asserts they agree), and a profile-name guard refusing `..` or a path.
