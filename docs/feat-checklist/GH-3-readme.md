---
type: FeatChecklist
slug: GH-3-readme
issue: 3
timestamp: 2026-09-17T00:00:00Z
---

# GH-3-readme — acceptance checklist   (7 proven · 0 manual · 0 failing)

- [x] The README leads with `pip install whatsapp-agent` and what the command does — first screen is the pitch, the install and a working `send`
- [x] Both layers are described, with the relay marked as a later release — "What this is part of"
- [x] Every shell example runs as written — all four run this session against the installed command, including `send --dry-run` with the token unset, which the README claims needs none
- [x] The Python example runs as written — `from whatsapp_agent import WhatsApp, Store, WhatsAppError` now works, because the package exports its surface rather than only its errors
- [x] The globals-before-subcommand gotcha is documented, with both forms shown — and both were run: `--profile work recv` exits 0, `recv --profile work` exits 2
- [x] Nothing describes a personal setup — the check greps the README for vault names, paths, "VPS" and the author's handle
- [x] The README cannot quietly rot — the check asserts every command it shows exists in `--help`, every name its Python example imports is exported, and that it still names the distribution, the optional extra, the token variable and the error table

## What changed beyond the README

`whatsapp_agent/__init__.py` now exports `WhatsApp`, `Sent`, `Store`, `CODES`, `resolve_token` and `state_dir` alongside the error types. The README promised a library; the package was only exporting its exceptions, so the documented import would have failed. `import whatsapp_agent` still does not pull in `requests` — that happens when a client is constructed.

## Findings

**FINDING-05 — closed.** Global options before the subcommand is now documented, with the failing form shown next to the working one.

**FINDING-09 · Minor · `README.md`** — the PyPI and version badges are missing, because the package is not published. #8 should add them once the name is live; a badge pointing at a non-existent project renders as an error.
