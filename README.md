# whatsapp-agent-cli

A relay that puts a coding agent in your pocket: a WhatsApp agent (WhatsApp Agent Platform, long-poll, single creator) on one side, a CLI agent such as Claude Code or Codex over a folder on the other. Read-only by default; write paths are declared per folder.

> **Status:** placeholder. The relay runs in a personal setup since 2026-09-06 and will be published here after the AI Tinkerers *Agents, Everywhere* hackathon (2026-09-12). Its first product is [`hisab-whatsapp`](https://github.com/mhmzdev/hisab-whatsapp), a plain-language ledger on the same channel.

What it will hold, in the order it exists today:

- long-poll loop with a stored offset, backoff on 429 and 503
- session reset and model switching owned by the relay, not the model
- a message store keyed by WhatsApp id, so quoted replies resolve after a reset
- voice notes transcribed before the agent sees them
- images and documents fetched and handed to the agent by path
- replies split under WhatsApp's 4,096-character cap, markdown converted to WhatsApp formatting
- a per-call deny list built from the folder listing, so a new folder is denied by default

## When something fails

Every failure names its code and exits with a number a script can branch on:

```
error [platform_rejected]: the platform refused this request; retrying will not help
```

`whatsapp-agent errors` lists them all; [`docs/errors.md`](docs/errors.md) says what to do about each.

## License

MIT.
