# whatsapp-agent-cli

**A client for the WhatsApp Agent Platform — a library first, with a command-line tool on top.**

[![PyPI](https://img.shields.io/pypi/v/wa-agent)](https://pypi.org/project/wa-agent/)
[![Python](https://img.shields.io/pypi/pyversions/wa-agent)](https://pypi.org/project/wa-agent/)
[![Tests](https://github.com/mhmzdev/whatsapp-agent-cli/actions/workflows/tests.yml/badge.svg?branch=develop)](https://github.com/mhmzdev/whatsapp-agent-cli/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](https://github.com/mhmzdev/whatsapp-agent-cli/blob/main/LICENSE)

Send and receive WhatsApp messages from a script, a cron job, a git hook, or a coding agent with shell access. It handles the parts that are tedious to get right — the long-poll and its cursor, per-method rate limits, the 4,096-character send cap, the two-hop media fetch, an error table where one code means "back off" and another means "this token is dead, stop", and voice notes turned into text by Gemini, OpenRouter, or fully offline on your own machine.

```bash
wa-agent send "deploy finished, 3 tests failing"
```

It knows nothing about coding agents, folders, permissions or models. It moves messages.

> **First product built on it: [Hisab](https://mhmzdev.github.io/hisab/)** — a ledger that texts back. Double-entry bookkeeping for small businesses, run entirely from WhatsApp. [More below.](#built-on-it-hisab)

## Contents

- [What it does differently](#what-it-does-differently)
- [Install](#install)
- [Get a token](#get-a-token)
- [Use it](#use-it)
- [Transcription](#transcription)
- [Use it from Python](#use-it-from-python)
- [Where it keeps things](#where-it-keeps-things)
- [When something fails](#when-something-fails)
- [Built on it: Hisab](#built-on-it-hisab)
- [Coming next: the relay](#coming-next-the-relay)
- [Contributing](#contributing)
- [License](#license)

## What it does differently

Sending a WhatsApp message is one HTTP call. What takes a real bot to get right is everything around it: the process that dies halfway through a batch, the platform that says slow down, the voice note that arrives when there is no key to transcribe it. Those behaviours are the point of this package. Each was learned running [Hisab](#built-on-it-hisab) against real messages, and each is pinned by the repo's check.

### Nothing is lost, nothing is stolen

| Behaviour | What it means for you |
|---|---|
| **The cursor moves after the batch** | It is saved only once a batch is delivered, and any message id already seen is skipped. A crash can repeat a message; it can never lose one |
| **One poller per token** | The platform allows a single long-poll and answers `409` when a second takes it. `recv` exits with `another_poller` rather than silently competing for your messages |
| **A dead token stops the loop** | A `401` exits `4` and is never retried. In `recv --follow`, a `429` or `503` backs off from 1s to 60s and keeps going. The two never look alike |
| **`doctor` cannot steal the poll** | Checking a setup with a real poll would take the long-poll from a running `recv`. `doctor` uses a read that cannot be a poll, so it is safe to run beside one |

### Sending and media

| Behaviour | What it means for you |
|---|---|
| **Long messages split cleanly** | Cut on paragraph boundaries under WhatsApp's 4,096-character cap, numbered `(i/n)`, with markdown converted to WhatsApp formatting |
| **A half-failed send tells you what arrived** | Every part that already went out is printed and recorded before a later one can fail, so a retry duplicates nothing |
| **Rate limits are built in** | Paced per method, with one retry past a `429`. You do not write the backoff |
| **Size caps are checked before the upload** | 5 MB an image, 500 KB a sticker, 16 MB anything else, refused locally without spending a request |
| **`--dry-run` shows exactly what would go out** | Needs no token and sends nothing |

### Voice notes, where the opinions are

| Behaviour | What it means for you |
|---|---|
| **You choose the provider, it never guesses** | `gemini` unless you say otherwise. A key for another provider is never spent because it was lying in your environment |
| **Offline is opt-in, never a fallback** | A default install has no offline engine. A missing key does not switch one on: `recv` warns once and delivers the note marked `transcribed: false` |
| **Nothing downloads behind your back** | A model comes only from `wa-agent model pull`, which says its size first. Never during `recv` |
| **A failed transcription is never passed off as speech** | The note is delivered marked, with the reason in `transcription_error`. An empty result or a provider's error message is an error, never words nobody said |
| **A weak transcript says so** | A locally transcribed note carries `transcribed_by`, so your code can weigh it. The docs say what the engine is bad at |
| **The message keeps its shape** | The words are added at `text.body`; `type`, `audio` and everything else are untouched, so code that already reads a message keeps working |

### Failures, and your machine

| Behaviour | What it means for you |
|---|---|
| **Every failure is a code** | One fixed line, an exit status a script can branch on, and a verdict on whether retrying helps. `wa-agent errors` prints the table |
| **The platform's words stay in one place** | They appear only on a `detail:` line, and a token or key is never printed in an error or by `doctor` |
| **Nothing lands in your working directory** | State lives under XDG, per profile, and downloaded models beside it. Downloads are swept after a day |
| **Secrets come from the environment** | Or from a token file. No flag takes one, so none reaches your shell history or the process list |
| **One dependency** | `requests`. The heavy things are extras you ask for |

## Install

```bash
pip install wa-agent
```

The package, the command and the module are all `wa-agent` / `wa_agent`. (This repository is named `whatsapp-agent-cli`; that name and `whatsapp-agent` both belong to unrelated projects on PyPI.)

That is the whole install: sending, receiving, media, and transcription through Gemini or OpenRouter, which needs only a key because it is an ordinary HTTP call. Transcribing offline is an extra you ask for. See [Transcription](#transcription).

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

`recv --transcribe` takes the same `--provider`. Without a key for it, it warns once and delivers voice notes marked `transcribed: false` rather than stopping. [More on transcription.](#transcription)

`recv --download` fetches each photo, document and voice note into the state directory as it arrives and adds a `path` to the message. It is opt-in because it puts a fetch inside the delivery loop; a download that fails is delivered marked with `download_error`, never dropped. With `--transcribe` as well, a voice note is fetched once, kept, and transcribed from that copy.

| Command | Does |
|---|---|
| `send <text>` | Send a message. Splits a long body on paragraph boundaries, numbers the parts `(i/n)`, converts markdown to WhatsApp formatting |
| `send --file <path>` | Upload and attach. `--media <id>` attaches something already uploaded |
| `send --dry-run` | Print exactly what would be sent, send nothing, need no token |
| `recv` | Messages since the last run. `--json` for one object per line, `--follow` to stream, `--typing` to show a typing indicator while you work, `--transcribe` (with `--provider`) to add words to voice notes, `--download` to keep photos and files as they arrive |
| `transcribe <file>` | Audio in, text out. Gemini or OpenRouter, chosen with `--provider`, or `--provider local` to run offline (see [Transcription](#transcription)) |
| `model pull [size]` | Download a Whisper model for `--provider local`: `tiny`, `base` (the default) or `small`. Says the size first. It is the only thing that ever downloads one |
| `media get <id>` | Download to the state directory, or `--out DIR`. Prints the path and nothing else |
| `media put <path>` | Upload, print the media id |
| `doctor` | Check a setup, a line each: Python, token, each transcription key, the local engine, state directory, creator. Says what to fix, exits `15` if anything fails. It never polls, so it is safe beside a running `recv`, but it does make real, free metadata requests to the platform and to every provider whose key is set in your environment |
| `errors` | The exit-code table |

Global options — `--token-file`, `--state-dir`, `--profile` — go **before** the subcommand, as in git:

```bash
wa-agent --profile work recv --follow     # yes
wa-agent recv --follow --profile work     # no: unrecognized argument
```

## Transcription

Three providers, and one rule: **you choose, it never guesses.**

| | Gemini | OpenRouter | Local |
|---|---|---|---|
| **Choose with** | nothing (the default), or `--provider gemini` | `--provider openrouter` | `--provider local` |
| **Needs** | `GEMINI_API_KEY` | `OPENROUTER_API_KEY` | no key |
| **Install** | nothing extra | nothing extra | `pip install "wa-agent[local]"`, then `wa-agent model pull` |
| **Cost and privacy** | billed by the provider; the audio goes to them | billed by the provider; the audio goes to them | free; nothing leaves your machine |
| **Marked in `recv --json`** | nothing added | nothing added | `"transcribed_by": "local:base"` |

```bash
export GEMINI_API_KEY='…'
wa-agent transcribe voice-note.ogg

export OPENROUTER_API_KEY='…'
wa-agent transcribe voice-note.ogg --provider openrouter    # --model takes an OpenRouter model id
```

### Offline, on your own machine

Nothing leaves the machine and nothing is billed. It is an extra because it is heavy (about 150 MB of dependencies) and a model is a separate download, so it takes three deliberate steps:

```bash
pip install "wa-agent[local]"                         # 1. the engine
wa-agent model pull                                   # 2. a model: says the size first; base is about 150 MB
wa-agent transcribe voice-note.ogg --provider local   # 3. ask for it: tiny, base or small; --model small
```

It is never chosen for you, not even when a key is missing: `--provider local` is a decision. Nothing downloads during `recv`. Models are kept in `$XDG_DATA_HOME/wa-agent/models/`, shared by every profile.

### When there is no key

Nothing is imposed on you, and nothing is used in its place:

| You run | With no key and no local engine |
|---|---|
| `wa-agent transcribe note.ogg` | Exits `12` (`no_transcription_key`), and the `detail:` line names the variable to set |
| `wa-agent recv --transcribe` | Warns once, up front, then delivers each voice note marked `transcribed: false` and keeps going |
| `wa-agent recv --transcribe --provider local` before `model pull` | The same: one warning that names the fix, notes delivered marked, and no download |

### What the local engine is bad at

- **Fine:** clear, accented English.
- **Poor:** Urdu, Roman Urdu, and speech that switches between languages. A small Whisper model tends to write fluent, confident English that was never said, rather than failing, so a wrong transcript looks exactly like a right one.
- **Slower** than an API call, and `recv` waits while it works.
- **So it is tagged:** `recv --json` adds `"transcribed_by": "local:base"` to a locally transcribed voice note, and adds nothing to a Gemini or OpenRouter one, so whatever reads a message can weigh it differently.
- **Three sizes only:** `tiny`, `base` and `small`. There is no English-only (`.en`) model, because it would turn Urdu into English even more confidently.

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

Nothing is written into your working directory. State lives at `$XDG_STATE_HOME/wa-agent/<profile>/` (or `~/.local/state/…`), holding the poll cursor, the message log and downloaded media. `--state-dir` moves it; `--profile` keeps two agents apart. Downloaded transcription models are kept apart from it, in `$XDG_DATA_HOME/wa-agent/models/` (or `~/.local/share/…`), because they are large and the same for every profile.

**One poller per token.** The platform allows a single long-poll per agent and answers `409` when a second one takes the cursor, so `recv` exits rather than silently competing for your messages.

## When something fails

Every failure names its code and exits with a number a script can branch on:

```
error [platform_rejected]: the platform refused this request; retrying will not help
detail: POST /messages: HTTP 400 error.code 131009 …
```

Not sure where a setup stands? `wa-agent doctor` checks it in one go and says what to fix.

`wa-agent errors` lists them all. [`docs/errors.md`](https://github.com/mhmzdev/whatsapp-agent-cli/blob/main/docs/errors.md) says what to do about each and which are worth retrying — the short version is that exit `7` is, and `4` and `6` never are.

## Built on it: Hisab

[![Hisab — a ledger that texts back](https://raw.githubusercontent.com/mhmzdev/hisab-whatsapp/main/showcase/hisab-cover.png)](https://mhmzdev.github.io/hisab/)

[**Hisab**](https://mhmzdev.github.io/hisab/) is a plain-language ledger you keep by texting WhatsApp — *"2500 coffee"* posts an entry, *"how much do I owe Metro?"* gets an answer — in English, Urdu or Roman Urdu, by voice, photo or text, with every entry checked by `hledger` before it is written.

It is where this package came from. The cursor that only advances after a batch, the dedup, the per-method rate limits and the dead-token exit were all learned running Hisab against real messages, then extracted here so nothing else has to learn them again. Hisab is the first product on this transport, and moves onto the published `wa-agent` package next.

The two repositories split the work cleanly:

| | [whatsapp-agent-cli](https://github.com/mhmzdev/whatsapp-agent-cli) (this) | [hisab-whatsapp](https://github.com/mhmzdev/hisab-whatsapp) |
|---|---|---|
| Is | the transport: messages, media, transcription | a product: a ledger with a model and six tools |
| Knows about | tokens, cursors, rate limits | accounts, entries, `hledger` |
| You use it | from a script, a cron job, or your own agent | by texting it |

## Coming next: the relay

The transport moves messages. The relay is what makes it an agent in your pocket.

```bash
wa-agent relay --folder ~/code/my-project     # coming soon
```

Text it from your phone — *"why is the deploy failing?"*, a screenshot of an error, a voice note describing a bug — and it runs a coding agent such as **Claude Code** over that folder and sends back what it says. The design is settled; the code starts once this release is out:

- **Read-only by default.** The agent can read the folder and nothing else. Writable paths are declared, never assumed, and a folder created later is denied until you say otherwise.
- **The relay owns the session.** Starting fresh, switching models and compacting a long conversation happen in the relay, before the agent is called, because none of them survive a non-interactive run otherwise.
- **Everything it hears, it can use.** Voice notes arrive as words, photos and files arrive by path, and a quoted reply arrives with the message it quoted — all from this package, underneath.
- **One command in this package, optional.** `pip install wa-agent` never makes you run it. The transport stays usable on its own, and the relay uses it exactly as your own scripts would.

Claude Code comes first, Codex after. Follow along on the [issues](https://github.com/mhmzdev/whatsapp-agent-cli/issues).

## Contributing

```bash
cp .env.example .env    # fill in your agent token, and a transcription key if you want it
make dev                # a virtualenv with this checkout installed
make check              # the check: no network, no token, a couple of seconds
make up                 # a live inbox: text your agent and watch it land, until Ctrl-C
make live               # a scripted round trip: send, wait for your reply, read it back
```

`make up` and `make live` keep their state in `.live-state/`, never your real one, and `make clean` removes it. `develop` is the trunk and PRs target it; `main` is what is published. Conventions live in [`AGENTS.md`](https://github.com/mhmzdev/whatsapp-agent-cli/blob/main/AGENTS.md).

## License

MIT.
