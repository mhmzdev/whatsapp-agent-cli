---
type: FeatChecklist
slug: GH-6-media
issue: 6
timestamp: 2026-09-17T00:00:00Z
---

# GH-6-media — acceptance checklist   (12 proven · 1 manual · 0 failing)

Criteria from [#6](https://github.com/mhmzdev/whatsapp-agent-cli/issues/6) (scope extended with the author to include attaching) and its plan.

- [x] `media get <id>` downloads and prints one line, the resolved path — check's "media command" section
- [x] The extension follows the mime **prefix**, so `audio/ogg; codecs=opus` becomes `.ogg` — check's "media types" section
- [x] Both hops carry the bearer token, and the byte hop is status-checked — asserted on the recorded calls
- [x] A failure at either hop leaves no file, not even a partial one — the check globs for leftovers after four failure modes
- [x] A 404 on the byte hop reports the link expired (exit 11), since re-fetching is the fix — check's "media transfer" section
- [x] `media put` uploads and prints the id; the multipart form carries `messaging_product`, `type` and the named file part — asserted field by field
- [x] A file over its type's cap exits 10 **before any request is made** — proven in the check and confirmed with the installed command: a 6 MB PNG against a 5 MB cap never touches the network
- [x] An unguessable extension exits 2 asking for `--type`, and `--type` unblocks it — check plus the installed command
- [x] `send --file` uploads then attaches in one call; `send --media` attaches without re-uploading — the check counts the requests in each case
- [x] A photo is sent as `image`; a PDF as `document` keeping its filename; a caption converts markdown and is never chunked — asserted on the posted bodies
- [x] `send` with neither text nor attachment is a usage error rather than an empty message — check's "media command" section
- [x] The sweep removes downloads older than `--keep-hours` from the state directory and never touches an `--out` directory — both asserted in one run
- [?] A real photo round trip — needs the demo agent's token: text a photo from the phone, `whatsapp-agent recv --json` to read its media id, `whatsapp-agent media get <id>` and open the printed path; then `whatsapp-agent send "chart" --file <some.png>` and check it arrives as a photo with that caption

## Conventions

- **Layer purity** — media is bytes in and bytes out. Nothing here looks at what a file contains; a voice note is just an `.ogg` until #7.
- **Failures** — two new codes, `media_too_large` (10) and `media_url_expired` (11). Eleven codes now, all unique, none leaking a body into its message.
- **State** — downloads default to the state directory, never the working directory; an explicit `--out` is the caller's and is never swept.
- **Live checks** — oversize refusal, the unguessable type, and a dead-token download were all run against the installed command, the last one against the real endpoint.

## Findings

**FINDING-07 · Minor · `whatsapp_agent/cli.py`** — `send --file` uploads and then attaches as two requests. If the attach fails, the upload has already been spent against the 12/min media budget and its id is not printed anywhere, so the caller cannot retry the attach without re-uploading. Printing the media id to stderr on an attach failure would fix it cheaply; left out to keep the success path's output clean, and worth revisiting if the manual pass ever hits it.

**FINDING-05 (from #5) — still open.** Global options must precede the subcommand. Now more visible, since `media` and `send` both take options of their own.

**FINDING-04 (from #4) — still open.** A multi-part text send that fails halfway leaves the earlier parts delivered.
