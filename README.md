# whatsapp-agent-cli

**A client for the WhatsApp Agent Platform — a library first, with a command-line tool on top.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Send and receive WhatsApp messages from a script, a cron job, a git hook, or a coding agent with shell access. It handles the parts that are tedious to get right — the long-poll and its cursor, per-method rate limits, the 4,096-character send cap, the two-hop media fetch, and an error table where one code means "back off" and another means "this token is dead, stop".

```bash
whatsapp-agent send "deploy finished, 3 tests failing"
```

It knows nothing about coding agents, folders, permissions or models. It moves messages.

## Install

```bash
pip install whatsapp-agent
```

The distribution is `whatsapp-agent`, the command is `whatsapp-agent`, the module is `whatsapp_agent`. (This repository is named `whatsapp-agent-cli`, which was already taken on PyPI by an unrelated project.)

Voice-note transcription is an optional extra, because it needs a speech-to-text provider and a key of its own:

```bash
pip install "whatsapp-agent[transcribe]"
```

## Get a token

In WhatsApp: **Settings → Agents → Create an agent → Chat info → API key.** An agent may only message its own creator — you — which is why there is no recipient management here.

```bash
export WHATSAPP_AGENT_TOKEN='…'        # or: whatsapp-agent --token-file ~/.wa-token …
```

## Use it

```bash
# say something to yourself
whatsapp-agent send "the backup finished"

# read what arrives, one JSON object per line, until you stop it
whatsapp-agent recv --follow --json

# attach a file; the text becomes its caption
whatsapp-agent send "this week's numbers" --file chart.png

# fetch something someone texted you, and open it
open "$(whatsapp-agent media get <media-id>)"
```

The first `recv` records who you are, after which `send` needs no `--to`.

| Command | Does |
|---|---|
| `send <text>` | Send a message. Splits a long body on paragraph boundaries, numbers the parts `(i/n)`, converts markdown to WhatsApp formatting |
| `send --file <path>` | Upload and attach. `--media <id>` attaches something already uploaded |
| `send --dry-run` | Print exactly what would be sent, send nothing, need no token |
| `recv` | Messages since the last run. `--json` for one object per line, `--follow` to stream, `--typing` to show a typing indicator while you work |
| `media get <id>` | Download to the state directory, or `--out DIR`. Prints the path and nothing else |
| `media put <path>` | Upload, print the media id |
| `errors` | The exit-code table |

Global options — `--token-file`, `--state-dir`, `--profile` — go **before** the subcommand, as in git:

```bash
whatsapp-agent --profile work recv --follow     # yes
whatsapp-agent recv --follow --profile work     # no: unrecognized argument
```

## Use it from Python

```python
from whatsapp_agent import WhatsApp, Store, WhatsAppError

client = WhatsApp(token)
for sent in client.send_iter("user:123", "**done** in 40s"):
    print(sent.id, sent.text)       # one per part, as each leaves

messages, cursor = client.poll(offset=None)
for message in messages:
    print(message["from"], message.get("text", {}).get("body"))
```

`send_iter` yields each part as it is delivered, so a failure halfway never hides what already arrived. `Store` is the message log and the cursor, keyed by the platform's own message ids.

## Where it keeps things

Nothing is written into your working directory. State lives at `$XDG_STATE_HOME/whatsapp-agent/<profile>/` (or `~/.local/state/…`), holding the poll cursor, the message log and downloaded media. `--state-dir` moves it; `--profile` keeps two agents apart.

**One poller per token.** The platform allows a single long-poll per agent and answers `409` when a second one takes the cursor, so `recv` exits rather than silently competing for your messages.

## When something fails

Every failure names its code and exits with a number a script can branch on:

```
error [platform_rejected]: the platform refused this request; retrying will not help
detail: POST /messages: HTTP 400 error.code 131009 …
```

`whatsapp-agent errors` lists them all. [`docs/errors.md`](docs/errors.md) says what to do about each and which are worth retrying — the short version is that exit `7` is, and `4` and `6` never are.

## What this is part of

Two layers, and this repository ships the first:

- **The transport** (here): messages, media, transcription. No opinions about what you do with them.
- **The relay** (later): reading a message, running a coding agent such as Claude Code over a folder, and sending back what it says. It will be a command in this same package, built on the transport, once the transport is published and stable.

The transport is also what [`hisab-whatsapp`](https://github.com/mhmzdev/hisab-whatsapp) — a plain-language ledger you text — will use in place of its own copy.

## Status

Working: `send`, `recv`, `media`, `errors` and the library behind them, each covered by a no-network check on Python 3.10 through 3.13.

Not yet: transcription ([#7](https://github.com/mhmzdev/whatsapp-agent-cli/issues/7)), the first PyPI release ([#8](https://github.com/mhmzdev/whatsapp-agent-cli/issues/8)), and the relay. Progress lives on [epic #1](https://github.com/mhmzdev/whatsapp-agent-cli/issues/1).

## Contributing

`develop` is the trunk and PRs target it; `main` is what is published. `python3 tests/smoke.py` is the check, and it runs with no network and no token. Conventions live in [`AGENTS.md`](AGENTS.md).

## License

MIT.
