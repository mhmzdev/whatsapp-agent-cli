# whatsapp-agent-cli — the four things you actually do.
#
#   make dev     a virtualenv with the package installed from this checkout
#   make check   the repo check: no network, no token, a couple of seconds
#   make live    a real round trip against a real agent, using your .env
#   make up      a live inbox: everything you send the agent lands here, until Ctrl-C
#   make clean   remove the virtualenv and build artifacts
#
# `make live` and `make up` are the only ones that talk to WhatsApp or spend anything.

# macOS still ships Python 3.9 as `python3`, which this package does not support.
# Pick the first interpreter that is actually new enough rather than failing inside
# pip with a message about a version nobody chose. Override with `make PYTHON=...`.
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11 python3.10 python3; do \
	command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null \
	&& echo $$p && break; done)

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
CLI := $(VENV)/bin/whatsapp-agent

.PHONY: help dev check live up clean

help:
	@grep -E '^#   make' $(MAKEFILE_LIST) | sed 's/^#   //'

$(VENV):
	@test -n "$(PYTHON)" || { echo "no Python 3.10+ found. Install one, or: make PYTHON=/path/to/python3.12 dev"; exit 1; }
	@echo "using $(PYTHON) ($$($(PYTHON) -V))"
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip

dev: $(VENV)
	$(PIP) install --quiet --editable .
	@echo "ready: $(CLI)"
	@$(CLI) --version

check:
	@test -n "$(PYTHON)" || { echo "no Python 3.10+ found. Install one, or: make PYTHON=/path/to/python3.12 check"; exit 1; }
	$(PYTHON) tests/smoke.py

live: dev
	@$(PY) tests/live.py $(ARGS)

# Follows, transcribes and downloads, into .live-state/ like `make live`, so it never
# touches your real state. Ctrl-C is the only way down, and it is a clean exit: the
# cursor stays at the last complete batch. Pass extra flags with ARGS="--json".
up: dev
	@test -f .env || { echo "no .env — cp .env.example .env and fill it in"; exit 3; }
	@echo "live inbox on the agent in .env. Photos and files land in .live-state/media. Ctrl-C to stop."
	@set -a; . ./.env; set +a; \
		$(CLI) --state-dir .live-state recv --follow --transcribe --download $(ARGS) \
		|| { status=$$?; [ $$status -eq 130 ] && echo "stopped." || exit $$status; }

clean:
	rm -rf $(VENV) dist build *.egg-info .live-state
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
