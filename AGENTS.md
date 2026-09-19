# whatsapp-agent-cli — agent guide

A relay that puts a coding agent in your pocket: a WhatsApp agent (Agent Platform, long-poll, single creator) on one side, a CLI agent such as Claude Code or Codex, run non-interactively over one folder, on the other. The CLI agent is the brain; the relay is transport plus session control. Read-only by default; write paths are declared per folder. This file is the canonical instructions for any coding agent (Claude Code reads it through `CLAUDE.md`; Codex and others read it directly). It is a router and a fact sheet: the README defines the product, the skills explain the process, the rules hold the conventions.

## Read in this order

1. This file — how to work here and the repo facts.
2. [`README.md`](README.md) — the product definition and the feature list, in the order the features exist today.
3. [`docs/INDEX.md`](docs/INDEX.md) — the progressive-disclosure root for every artifact; each directory has its own `INDEX.md`.
4. [`.agents/rules/`](.agents/rules/) — conventions, one file per topic, each with a `paths:` frontmatter naming its area. Claude Code loads them through the `.claude/rules` symlink.
   - [`privacy.md`](.agents/rules/privacy.md) — nothing from the author's own setup enters this repo
   - [`releases.md`](.agents/rules/releases.md) — `develop` is the trunk, landing on `main` publishes to PyPI
5. The code, starting from the module the task names; `wa_agent/__init__.py` lists the names a dependent imports.

Docs follow the Open Knowledge Format: markdown, a small YAML frontmatter with `type`, an `INDEX.md` per directory, plain links as the graph.

## Repo map

```
README.md        the product definition — what the relay holds, in the order it exists today; it is also the PyPI page
CHANGELOG.md     what each release shipped; written in the bump PR, never in a feature PR
Makefile         make help · dev · check · live · up · clean
.env.example     every variable the code reads, explained inline (the check enforces the list)
.github/workflows/  tests.yml (the check on every PR) and release.yml (main -> PyPI, tag, GitHub Release)
scripts/         bump_version.py — the only way the version moves
AGENTS.md        this file; CLAUDE.md imports it
.agents/skills/  the lifecycle skills (.claude/skills is a symlink)
.agents/rules/   conventions (.claude/rules is a symlink)
docs/            errors.md (every exit code and what to do about it), brainstorm/, specs/, exec-plans/{backlog,active,completed,superseded},
                 feat-checklist/, INDEX.md at every level
```

```
wa_agent/
  __init__.py    the package version, and the names a dependent imports
  errors.py      THE failure registry: every code, its message and its exit status; AuthError is permanent
  state.py       where the token comes from (env, then --token-file), where state lives and where models live (XDG, never the cwd)
  envfile.py     ./.env for the CLI only: parse KEY=VALUE lines, fill the environment's gaps (the shell wins), record each variable's source
  client.py      WhatsApp: the HTTP client — poll, typing, download, upload, send_media, send_iter/send, probe_token; every call
                 paced by the rate limiter, retried once past a 429, and classified into a code
  ratelimit.py   one rolling 60s window per platform method (messages, statuses, updates, media_post, media_get)
  text.py        markdown → WhatsApp formatting, and splitting a long body into numbered parts under the cap
  media.py       mime → extension, per-type size caps, image vs document
  store.py       Store: the message log keyed by platform id, the poll cursor, the recorded creator
  transcribe.py  voice notes → text: gemini and openrouter over plain HTTP, local through local.py; the provider is never guessed
  local.py       the offline engine (the `local` extra, faster-whisper): `model pull`, readiness checks, never downloads mid-recv
  doctor.py      `wa-agent doctor`: one line a check, never polls, never writes
  cli.py         the argparse surface: send, recv, media get/put, transcribe, model pull, doctor, errors; reads ./.env unless
                 --no-env-file and names each variable's source on stderr (the `env:` line); failures leave through _fail
  __main__.py    python -m wa_agent
tests/smoke.py   the check: no network, no token, no writes outside a temp dir
tests/live.py    a real round trip against a real agent (make live); reads .env, so it is the owner's to run
```

## Not hisab-whatsapp

The relay is where [`hisab-whatsapp`](https://github.com/mhmzdev/hisab-whatsapp) came from, but it is a different product: the user is a developer, there is no ledger, and there is no model API loop of its own. Do not reuse hisab's tool loop. Do reuse its transport knowledge (long-poll, dedup, rate limits, dead-token exit, chunking, transcription providers) — read hisab's `hisab/store.py` for the shape, and copy only through the privacy rule. Hisab itself now runs on this package: `hisab/wa.py` is its adapter, and the best example of a library consumer.

## Non-negotiables

- **Read-only by default.** A folder the config does not name as writable is denied to the CLI agent. The deny list is built from the folder listing at call time, so a new folder is denied until declared. The relay never grants the agent more than the config says.
- **The relay owns session control.** Reset and model choice happen in the relay before the agent is called; in-agent `/clear` and `/model` do not survive a non-interactive call.
- **Transport invariants:** skip a message id already in the store; advance the offset only after the batch; back off on 429 and 503; one poller per agent token (409 means another poller); a 401, or a 400 with `error.code` 100, means the token is dead — exit, never retry forever; split replies under WhatsApp's 4,096-character cap.
- **Voice notes are transcribed before the agent sees them;** a failed transcription is reported to the user, never handed to the agent as if they had said it.
- **Privacy.** Nothing from the author's personal vault, VPS, tokens, WhatsApp creator id, folder names or skill names enters this repo, an issue, a PR, a doc or a commit message. See `.agents/rules/privacy.md`. Example configs use a fake project.
- **Secrets only from the environment**, from `./.env` in the working directory, or from a token file outside the repo; never committed, never in an example. `./.env` is read by the CLI only, never by the library (`import wa_agent` reads no file from anyone's working directory). It only fills gaps: the shell always wins, and for the token the order is shell, `--token-file`, `./.env`. Sources are named on stderr, values never; `--no-env-file` turns it off. This reverses the earlier rule that the CLI never loaded `.env` (#44).

## Commands

| What | Command |
|---|---|
| The check (run before calling anything done) | `python3 tests/smoke.py` |
| Install for development | `make dev` (a `.venv` with this checkout installed), or `pip install -e .`; add `[local]` for offline transcription |
| A live round trip against your own agent (reads `.env`; one poller per token) | `make live`, or `make up` for a live inbox |
| Bump the version before a promote | `python3 scripts/bump_version.py patch\|minor\|major` |
| Release | merge a promote PR `develop → main`; `release.yml` publishes to PyPI, tags `v<version>` and cuts the GitHub Release |

## How we work — the lifecycle

Skills live in `.agents/skills/` (`.claude/skills` is a symlink to it); rules live in `.agents/rules/` (`.claude/rules` is a symlink to it). Put a new convention in its own rule file with a `paths:` frontmatter and list it under "Read in this order"; never create a real `.claude/rules/` directory. Each arrow is a human gate: finish, summarise, offer the next skill by name, wait.

    A  /brainstorm → /grill-me → /to-spec → /file-an-issue → /create-plan → /implement → /review → /open-pr
    B  <GitHub issue> → (/grill-me if the WHAT is contested) → /create-plan → /implement → /review → /open-pr

Small, low-risk work may skip stages; say which and why. One slug travels every stage (`GH-<N>-<topic>` once an issue exists). **Tickets are GitHub issues, never local files.** The full contract: `.agents/skills/README.md`.

Artifacts: `docs/brainstorm/` · `docs/specs/` · `docs/exec-plans/{backlog,active,completed,superseded}` · `docs/feat-checklist/`. Each directory gets its `INDEX.md` from the first skill that writes there.

## Repo facts (read by the skills)

```yaml
repo: mhmzdev/whatsapp-agent-cli
trunk: develop                   # PRs target this; never push to it directly
release_branch: main             # develop -> main is the release; release.yml publishes to PyPI
dist_name: wa-agent             # PyPI name, import wa_agent, command wa-agent — whatsapp-agent-cli and whatsapp-agent are both taken
issues_repo: mhmzdev/whatsapp-agent-cli
project_board: 2                 # owner mhmzdev — "WA-CLI"
board_fields:
  Status: [Backlog, Ready, In progress, In review, Done]
  Priority: [P0, P1, P2]
  Size: [XS, S, M, L, XL]
check: "python3 tests/smoke.py"
labels: read with `gh label list --repo mhmzdev/whatsapp-agent-cli`; apply only what exists, none is fine
branch: "GH-<N>-<kebab-topic>"   # or <kebab-topic> without an issue
pr:
  base: develop
  body: fixed sections — Why · Change Summary · Major Impact · Linked Issue · Test Plan · Deploy prerequisites (when needed)
  attribution: keep              # commits and PR bodies carry the Claude trailer and session link, as in git log
docs:
  brainstorm: docs/brainstorm
  specs: docs/specs
  exec_plans: docs/exec-plans
  feat_checklist: docs/feat-checklist
```

Vocabulary: **relay** (this program: poll, transcribe, fetch media, control the session, call the agent, reply), **agent** or **CLI agent** (Claude Code, Codex — the brain, run non-interactively), **WhatsApp agent** (the Agent Platform bot the relay polls), **creator** (the one person that WhatsApp agent may message), **folder** (the directory the CLI agent runs in), **write path** (a folder or file the config declares writable), **session** (the CLI agent's resumable conversation id), **store** (the message log keyed by WhatsApp id), **reset** (a new session minted by the relay).
