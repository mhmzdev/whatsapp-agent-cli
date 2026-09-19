# whatsapp-agent-cli

**A client for the WhatsApp Agent Platform — a library first, with a command-line tool on top.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Send and receive WhatsApp messages from a script, a cron job, a git hook, or a coding agent with shell access. It handles the parts that are tedious to get right — the long-poll and its cursor, per-method rate limits, the 4,096-character send cap, the two-hop media fetch, and an error table where one code means "back off" and another means "this token is dead, stop".

```bash
wa-agent send "deploy finished, 3 tests failing"
```

It knows nothing about coding agents, folders, permissions or models. It moves messages.

## Install

```bash
pip install wa-agent
```

The package, the command and the module are all `wa-agent` / `wa_agent`. (This repository is named `whatsapp-agent-cli`; that name and `whatsapp-agent` both belong to unrelated projects on PyPI.)

Transcription needs no extra install — only a key, because it is an ordinary HTTP call:

```bash
export GEMINI_API_KEY='…'
wa-agent transcribe voice-note.ogg
```

## Get a token

In WhatsApp: **Settings → Agents → Create an agent → Chat info → API key.** An agent may only message its own creator — you — which is why there is no recipient management here.

```bash
export WHATSAPP_AGENT_TOKEN='…'        # or: wa-agent --token-file ~/.wa-token …
```

## Use it

```bash
# say something to yourself
wa-agent send "the backup finished"

# read what arrives, one JSON object per line, until you stop it
wa-agent recv --follow --json

# attach a file; the text becomes its caption
wa-agent send "this week's numbers" --file chart.png

# fetch something someone texted you, and open it
open "$(wa-agent media get <media-id>)"
```

The first `recv` records who you are, after which `send` needs no `--to`.

A voice note keeps its shape and gains the words, so code that reads `text.body` finds them and nothing about the message is lost:

```json
{"id": "wamid.A", "type": "audio", "audio": {"id": "media-1", "voice": true},
 "text": {"body": "call me back at six"}, "transcribed": true}
```

Without a key, `recv --transcribe` warns once and delivers voice notes marked `transcribed: false` rather than stopping.

`recv --download` fetches each photo, document and voice note into the state directory as it arrives and adds a `path` to the message. It is opt-in because it puts a fetch inside the delivery loop; a download that fails is delivered marked with `download_error`, never dropped. With `--transcribe` as well, a voice note is fetched once, kept, and transcribed from that copy.

| Command | Does |
|---|---|
| `send <text>` | Send a message. Splits a long body on paragraph boundaries, numbers the parts `(i/n)`, converts markdown to WhatsApp formatting |
| `send --file <path>` | Upload and attach. `--media <id>` attaches something already uploaded |
| `send --dry-run` | Print exactly what would be sent, send nothing, need no token |
| `recv` | Messages since the last run. `--json` for one object per line, `--follow` to stream, `--typing` to show a typing indicator while you work, `--transcribe` to add words to voice notes, `--download` to keep photos and files as they arrive |
| `transcribe <file>` | Audio in, text out. Gemini today; offline is [#20](https://github.com/mhmzdev/whatsapp-agent-cli/issues/20) |
| `media get <id>` | Download to the state directory, or `--out DIR`. Prints the path and nothing else |
| `media put <path>` | Upload, print the media id |
| `errors` | The exit-code table |

Global options — `--token-file`, `--state-dir`, `--profile` — go **before** the subcommand, as in git:

```bash
wa-agent --profile work recv --follow     # yes
wa-agent recv --follow --profile work     # no: unrecognized argument
```

## Use it from Python

```python
from wa_agent import WhatsApp, Store, WhatsAppError

client = WhatsApp(token)
for sent in client.send_iter("user:123", "**done** in 40s"):
    print(sent.id, sent.text)       # one per part, as each leaves

messages, cursor = client.poll(offset=None)
for message in messages:
    print(message["from"], message.get("text", {}).get("body"))
```

`send_iter` yields each part as it is delivered, so a failure halfway never hides what already arrived. `Store` is the message log and the cursor, keyed by the platform's own message ids.

## Where it keeps things

Nothing is written into your working directory. State lives at `$XDG_STATE_HOME/wa-agent/<profile>/` (or `~/.local/state/…`), holding the poll cursor, the message log and downloaded media. `--state-dir` moves it; `--profile` keeps two agents apart.

**One poller per token.** The platform allows a single long-poll per agent and answers `409` when a second one takes the cursor, so `recv` exits rather than silently competing for your messages.

## When something fails

Every failure names its code and exits with a number a script can branch on:

```
error [platform_rejected]: the platform refused this request; retrying will not help
detail: POST /messages: HTTP 400 error.code 131009 …
```

`wa-agent errors` lists them all. [`docs/errors.md`](docs/errors.md) says what to do about each and which are worth retrying — the short version is that exit `7` is, and `4` and `6` never are.

## What this is part of

Two layers, and this repository ships the first:

- **The transport** (here): messages, media, transcription. No opinions about what you do with them.
- **The relay** (later): reading a message, running a coding agent such as Claude Code over a folder, and sending back what it says. It will be a command in this same package, built on the transport, once the transport is published and stable.

The transport is also what [`hisab-whatsapp`](https://github.com/mhmzdev/hisab-whatsapp) — a plain-language ledger you text — will use in place of its own copy.

## Status

Working: `send`, `recv`, `media`, `transcribe`, `errors` and the library behind them, each covered by a no-network check on Python 3.10 through 3.13.

Not yet: offline transcription ([#20](https://github.com/mhmzdev/whatsapp-agent-cli/issues/20)), the first PyPI release ([#8](https://github.com/mhmzdev/whatsapp-agent-cli/issues/8)), and the relay. Progress lives on [epic #1](https://github.com/mhmzdev/whatsapp-agent-cli/issues/1).

## Contributing

```bash
cp .env.example .env    # fill in your agent token, and a Gemini key if you want transcription
make dev                # a virtualenv with this checkout installed
make check              # the check: no network, no token, a couple of seconds
make up                 # a live inbox: text your agent and watch it land, until Ctrl-C
make live               # a scripted round trip: send, wait for your reply, read it back
```

`make up` and `make live` keep their state in `.live-state/`, never your real one, and `make clean` removes it. `develop` is the trunk and PRs target it; `main` is what is published. Conventions live in [`AGENTS.md`](AGENTS.md).

## License

MIT.
