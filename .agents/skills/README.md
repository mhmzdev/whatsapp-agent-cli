# Skills — the relay lifecycle

Agent-agnostic skills. Canonical location: `.agents/skills/` (read by Codex and any agent that honours it); `.claude/skills` is a symlink to it, so Claude Code sees the same files. Conventions for the code live beside the skills in `.agents/rules/`, linked the same way through `.claude/rules`. Repo facts live in `AGENTS.md` (which `CLAUDE.md` imports). **Every skill here honours this file.**

## The lifecycle

Two lifecycles, each arrow a human gate (finish, summarise, offer the next skill by name, wait — never auto-chain). One slug from first artifact to PR.

```
A  /brainstorm → /grill-me → /to-spec → /file-an-issue → /create-plan → /implement → /review → /open-pr
B  <a GitHub issue> → (/grill-me if the WHAT is contested) → /create-plan → /implement → /review → /open-pr
```

| Skill | Does | Writes |
|---|---|---|
| `brainstorm` | Explore WHAT and WHY before a plan | `docs/brainstorm/<slug>.md` |
| `grill-me` | Stress-test an idea, spec, plan or issue, one question at a time | the artifact it was pointed at |
| `to-spec` | Turn a hardened discussion into a numbered WHAT/WHY contract | `docs/specs/<NNN>-<slug>.md` |
| `file-an-issue` | File GitHub issues: parent + tracer-bullet sub-issues from a spec, or one standalone issue | GitHub issues only, never local files |
| `create-plan` | `file:line`-grounded implementation plan with provable criteria | `docs/exec-plans/backlog/<slug>.md` |
| `implement` | Execute a plan phase by phase, `backlog/ → active/ → completed/` | code + the plan's status |
| `review` | Acceptance checklist from intent plus diff, each criterion verified at the cheapest honest layer | `docs/feat-checklist/<slug>.md` |
| `open-pr` | The PR, with the fixed body shape and `Closes #N` | the PR |
| `refine-approach` | Sharpen a brainstorm, spec or plan in place | the doc |

Small, low-risk work may skip stages. Say which and why.

## Contract 1 — repo facts are read, never baked in

Facts (trunk, check command, board, labels, docs paths, vocabulary) come from **`AGENTS.md` → Repo facts**. A fact marked `undecided` or `none yet` is asked or derived (`gh repo view`, `git`, the manifest), stated in one message and confirmed once — then written back into `AGENTS.md`. Never invent.

## Contract 2 — the slug

`GH-<N>-<kebab-topic>` once an issue exists, else `<kebab-topic>`. Brainstorm, spec, plan, checklist and branch share it. A skill that finds an earlier-stage file for the slug reads it first. Issue titles carry the topic, so keep them kebab-able (`Quoted reply resolves after a reset`, not `Bug`).

## Contract 3 — behaviour

- **Human gates.** Every arrow is a hand-off with a question, one at a time, multiple choice with a recommended default.
- **Read before you ask.** If the answer is in the repo, find it.
- **Never destroy work.** No `reset --hard`, no force push, no `git add -A`, stop on divergence.
- **No fabricated references.** Every `file:line`, issue number and PR number was read this run.
- **Privacy is a rule, not a preference.** `.agents/rules/privacy.md`: nothing from the author's own vault, server, tokens, creator id, folder names or skill names enters this repo, an issue, a PR, a doc or a commit message.

## Contract 4 — one owner per board transition

Project board: see `AGENTS.md` → `project_board`. While it reads `undecided`, `file-an-issue` asks which board before creating anything. Status options are expected to be `Todo · In progress · Done`; read the real ones with `gh project field-list`.

| Transition | Owner |
|---|---|
| → Todo | `file-an-issue`, at creation |
| → In progress | `implement` (on the human's say-so) |
| → Done | the merge, via the PR's `Closes #N`. Never a skill |

`create-plan` and `review` do not move the card. A plan is a contract: `create-plan` leaves no open question; `implement` refuses a plan that carries one.
