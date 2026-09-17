---
description: Branches, versioning and what CI does — develop is the trunk, landing on main publishes to PyPI.
paths:
  - ".github/**"
  - "pyproject.toml"
  - "scripts/**"
---

# Branches, versions, releases

## Two branches

| Branch | Is | Receives |
|---|---|---|
| `develop` | the trunk, and the repo's default branch | every feature PR |
| `main` | production: whatever is published on PyPI | only a promote PR from `develop` |

A feature branch is cut from `develop` and its PR targets `develop`. Nobody pushes to either branch directly. The promote PR (`develop → main`) **is** the release: merging it runs `release.yml`.

## Versioning

SemVer, one source of truth: `version` in `pyproject.toml`. Nothing else stores a version — the package reports its own with `importlib.metadata.version("whatsapp-agent")`, and the git tag is written by CI from that field.

- `0.1.0` is the first published release. Pre-`1.0.0` means the API can still move.
- `1.0.0` when the API is stable — the earliest honest moment is after hisab-whatsapp has migrated onto it and nothing had to change.
- Bump on `develop`, before the promote PR: `python3 scripts/bump_version.py patch|minor|major`. One bump per release, not one per PR.

## What CI does

**`tests.yml`** — every PR into `develop` or `main`, and every push that lands on them. Runs the repo check on Python 3.10 through 3.13, with a `tests-passed` job aggregating the matrix into the single context branch protection requires. On a PR into `main` it also refuses a promote whose version still matches `main`'s, unless the PR carries the `no-release` label (a docs-only promote).

**`release.yml`** — on every push to `main`. Reads the version from `pyproject.toml`; if `v<version>` is already tagged it no-ops, so a `no-release` promote publishes nothing. Otherwise: build, `twine check`, install the wheel in a clean venv and run `whatsapp-agent --version`, publish to PyPI, then tag `v<version>` and create the GitHub Release with the built files attached. PyPI comes before the tag on purpose — a failed upload leaves no tag, so the next push retries the same version.

Publishing uses **PyPI trusted publishing** (OIDC): no API token lives in this repo's secrets. One-time setup on PyPI, by a human: project → Publishing → add a GitHub publisher for `mhmzdev/whatsapp-agent-cli`, workflow `release.yml`, no environment.

## Rules for agents

- Never push to `develop` or `main`; open a PR.
- Never create a tag or a GitHub Release by hand. `release.yml` owns both, and a hand-made tag makes the workflow skip the real release.
- Never bump the version inside a feature PR unless that PR *is* the bump.
- Never rename the `tests-passed` job in `tests.yml` — the branch rulesets require that one context by name, and renaming it silently unprotects both branches. It aggregates the `check` matrix, so the matrix itself can change freely.
- The distribution name is `whatsapp-agent` (the repo is `whatsapp-agent-cli`; that name was already taken on PyPI by an unrelated project).
