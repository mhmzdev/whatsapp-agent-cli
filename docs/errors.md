---
type: Reference
title: Exit codes
description: Every way whatsapp-agent can fail, what it means, and whether retrying helps.
tags: [errors, reference]
timestamp: 2026-09-17T00:00:00Z
---

# Exit codes

Every failure prints one line naming its code, and exits with a number a script can branch on:

```
error [platform_rejected]: the platform refused this request; retrying will not help
detail: POST /messages: HTTP 400 error.code 131009 …
```

The first line is fixed text you can search for. The `detail:` line is for a human reading their own terminal — it carries the platform's own words, and it is the only place an HTTP body ever appears. `WHATSAPP_AGENT_DEBUG=1` adds a traceback.

`whatsapp-agent errors` prints this table from the installed package, so it is always the version you are running.

## The table

| Code | Exit | Retry? | What happened | What to do |
|---|---|---|---|---|
| `bad_usage` | 2 | no | The arguments do not make sense: a missing file, an unguessable file type, a profile that looks like a path, or a `send` with nothing to send | Read the message; it names the argument. Remember that global options go **before** the subcommand: `whatsapp-agent --state-dir X recv` |
| `no_token` | 3 | no | No token in `WHATSAPP_AGENT_TOKEN`, and either no `--token-file` or a file that is missing or empty | Export the token, or point `--token-file` at a file containing it and nothing else |
| `auth` | 4 | **never** | The platform rejected the token itself — HTTP 401, or 400 with `error.code` 100 | Get a fresh token from the WhatsApp app (Settings → Agents → your agent → API key). A retry with the same token will fail identically, so a long-running loop should exit on this |
| `not_implemented` | 5 | no | The subcommand exists but its feature has not landed yet; the message names the issue tracking it | Follow the issue, or use another command |
| `platform_rejected` | 6 | no | The platform refused this specific request: a bad recipient, an unsupported media type, a malformed body | Read the `detail:` line — it carries the platform's `error.code`. The same request will be refused again |
| `platform_unavailable` | 7 | **yes** | A network failure, a 5xx, or a 429 that survived one backoff | Retry, with a delay. `recv --follow` already does this for you, backing off from 1s to a 60s cap |
| `no_recipient` | 8 | no | `send` had no `--to`, and no creator has been recorded yet | Pass `--to user:<id>`, or run `recv` once: the first message it receives records the creator, after which `--to` is optional |
| `another_poller` | 9 | no | Another process is polling this token. The platform allows exactly one, and answers 409 when a newer poll replaces an older one | Stop the other poller. Two on one token steal messages from each other silently, which is why this exits rather than warning |
| `media_too_large` | 10 | no | The file is over the platform's cap for its type: 5 MB an image, 500 KB a sticker, 16 MB anything else. Checked locally, before the upload is attempted | Shrink the file, or send it as a document rather than a photo |
| `media_url_expired` | 11 | no | The download link from the media metadata has expired. The media id has not | Run `media get <id>` again; it fetches a fresh link |
| `internal` | 70 | no | Something unforeseen. This is the fallback that keeps a traceback away from a caller | Re-run with `WHATSAPP_AGENT_DEBUG=1` for the traceback, and please open an issue with it |

Exit `130` is the conventional one for Ctrl-C, not a failure: `recv --follow` uses it after finishing the batch it is on.

## For a script

The only distinction most callers need:

```bash
whatsapp-agent send "deploy finished"
case $? in
  0)  ;;                      # sent
  7)  sleep 30; retry ;;      # the platform, not you
  4)  alert "token is dead" ;;  # never retries
  *)  alert "look at it" ;;   # everything else is a real problem
esac
```

## Adding a code

One row in `CODES` in [`whatsapp_agent/errors.py`](../whatsapp_agent/errors.py), with an exit status nothing else uses, and one row here. `python3 tests/smoke.py` fails and names the code if either is missing, or if a row here names a code that does not exist.
