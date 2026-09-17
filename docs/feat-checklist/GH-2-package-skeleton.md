---
type: FeatChecklist
slug: GH-2-package-skeleton
issue: 2
timestamp: 2026-09-17T00:00:00Z
---

# GH-2-package-skeleton — acceptance checklist   (8 proven · 1 manual · 0 failing)

Criteria from [#2](https://github.com/mhmzdev/whatsapp-agent-cli/issues/2) and the plan. Everything marked `[x]` was run this session against the working tree; the installed-package checks used a venv built from this branch.

- [x] `pip install -e .` then `whatsapp-agent --version` prints `whatsapp-agent 0.1.0` — run in a fresh venv
- [x] `whatsapp-agent --help` lists `send`, `recv`, `media`, `transcribe` — run, and asserted in the check's "cli surface" section
- [x] `pyproject.toml` names the distribution `whatsapp-agent` at version `0.1.0` — asserted in the check's "version" section, which also fails if the installed version and the declared one disagree
- [x] Token resolution is env first, then `--token-file`; missing, empty and unreadable all exit 3 with one line and no traceback — check's "token" section, which also asserts the token's own text never reaches a message
- [x] State directory created on first use, mode 0700, never derived from the working directory — check's "state dir" section, resolved from a temporary cwd with a temporary `HOME`; also covers `XDG_STATE_HOME`, `--profile`, `--state-dir`, and refuses a path-like profile
- [x] Every subcommand stub exits 5 naming its issue, never 0; bad usage and no-subcommand exit 2 — check's "cli surface" section, and confirmed against the installed command
- [x] `tests/smoke.py` runs with no network and no token, and `check:` in `AGENTS.md` names it — run repeatedly this session, including from the installed package
- [x] The "no check yet" fallback is gone from `tests.yml`; the workflow now runs the check unconditionally — `grep -c 'does not exist yet' .github/workflows/tests.yml` prints 0
- [x] The built wheel installs in a clean venv and runs — `python -m build` → `twine check` PASSED for both artifacts → clean venv → `whatsapp-agent --version`
- [?] CI is green on all four Python versions — the check ran locally on 3.11 only; the matrix proves 3.10, 3.12 and 3.13 when the PR opens

## Conventions

- **Layer purity** — nothing in `whatsapp_agent/` knows about agents, folders, sessions, models or subprocesses. The only matches for those words are the docstrings explaining the boundary.
- **Failures** — five codes, unique exit statuses, fixed messages. The check fails if a message ever contains `Traceback`, `HTTP`, an error body or a provider name. A traceback prints only when `WHATSAPP_AGENT_DEBUG` is set.
- **Privacy** — no path from the author's machine, no token, no personal reference in code, tests or packaging.
- **Dependencies** — exactly one runtime dependency, and `import whatsapp_agent` does not pull it in at import time.

## Findings

**FINDING-01 · Minor · `pyproject.toml:31`** — `requests>=2.32` is declared but nothing imports it yet; the first HTTP call arrives in #4. Leaving it is the plan's settled decision (it is the transport's dependency, and #4 is the next ticket), and it costs a dependent one well-known package for at most one ticket's duration. Removing it now would mean editing the dependency list again immediately. Recommend leaving it; noted so it is a decision rather than an oversight.

**FINDING-02 · Minor · `.github/workflows/tests.yml:34`** — CI installs `pip install -e .` without the `transcribe` extra, so `google-genai` is absent in CI. Correct today (nothing imports it) and it keeps the matrix fast, but #7 must either add the extra to the workflow or prove the absent-extra path explicitly, which its own criteria already ask for.

## Deviations from the plan

Both recorded in the plan's "What actually happened" section: the state directory does not raise when it resolves inside the working directory (that guard would break running from `~`, and the real requirement — never deriving the path from the cwd — is what the check proves), and `auth` is a fifth code because `AuthError` needs one.
