---
type: ExecPlan
slug: GH-6-media
issue: 6
status: completed
open_questions: none
---

# feat: media — photos and documents in and out, and send learns to attach          ✅ COMPLETED — 2026-09-17

## Problem

[#6](https://github.com/mhmzdev/whatsapp-agent-cli/issues/6) closes the gap `recv` leaves open. A photo or a PDF arriving on WhatsApp reaches a caller today as a media id and nothing else — the bytes need a two-hop fetch nobody outside this package should have to write. In the other direction, a caller who wants to send a chart or a log file has no way to do it at all.

**Scope extended with the author (2026-09-17):** the ticket also teaches `send` to attach, because an upload id that nothing can use is not a feature. `send --media <id>` attaches an existing upload; `send --file <path>` uploads and attaches in one call.

## Approach

**Download is two hops.** `GET /media/<id>` returns metadata carrying a short-lived `url`; the bytes come from that url, with the same bearer token. Both hops get their status checked — the old bash poller checked neither, which is how a failed fetch became a half-written file. The mime type is matched on its **prefix**, because the platform sends values like `audio/ogg; codecs=opus`; that detail is `hisab/wa.py:201`, learned the hard way.

**The file lands in the state directory** (`media/<id>.<ext>`) unless `--out` says otherwise, keeping with the rule that nothing is written into the caller's working directory by default. The path is printed on stdout and nothing else is, so `open "$(whatsapp-agent media get <id>)"` works.

**Sweeping.** Downloads accumulate. A `media` call sweeps files older than `--keep-hours` (default 24) from the state directory's `media/` first, so long-running use does not fill a disk. Files written to an explicit `--out` are the caller's business and are never swept.

**Upload caps are checked before the request.** The platform's limits are 5 MB for an image, 500 KB for a sticker and 16 MB otherwise; a file over its cap is refused locally with a new `media_too_large` code rather than spending a rate-limited request to be told the same thing. The type comes from the extension via `mimetypes`, with `--type` to override.

**Attaching.** A media message is `{"type": "image", "image": {"id": …, "caption": …}}`, or `document` with a `filename` so the recipient sees a name rather than a hash. Which of the two depends on the mime prefix: `image/*` is an image, everything else is a document. The text argument becomes the caption, and is therefore optional when attaching — `send --file chart.png` with no text is valid, which means `text` becomes `nargs="?"` and a bare `send` with neither text nor attachment is a usage error.

**What does not change:** a caption is not chunked. The platform caps a caption far below a text body, and silently splitting an attachment's caption across parts would be worse than refusing; over-long captions are left to the caller, and only the text path chunks.

## Success criteria

- [x] `media get <id>` downloads and prints one line, the path — `verify: python3 tests/smoke.py`
- [x] The extension follows the mime prefix, so `audio/ogg; codecs=opus` becomes `.ogg` — `verify: python3 tests/smoke.py`
- [x] A failed metadata hop or a failed byte hop leaves no file behind and exits non-zero — `verify: python3 tests/smoke.py`
- [x] A 404 on the byte hop reports that the url expired, since re-fetching is the fix — `verify: python3 tests/smoke.py`
- [x] `media put <path>` uploads and prints the id; the request carries `messaging_product`, `type` and the file part — `verify: python3 tests/smoke.py`
- [x] A file over its type's cap exits with `media_too_large` **before** any request is made — `verify: python3 tests/smoke.py`
- [x] `send --media <id>` attaches; `send --file <path>` uploads then attaches; both accept an optional caption — `verify: python3 tests/smoke.py`
- [x] An image is sent as `image`, a PDF as `document` carrying its filename — `verify: python3 tests/smoke.py`
- [x] `send` with neither text nor attachment is a usage error, not an empty message — `verify: python3 tests/smoke.py`
- [x] Media calls are paced on their own 12/min windows, upload and download separately — `verify: python3 tests/smoke.py`
- [x] Files older than `--keep-hours` are swept from the state directory, and an `--out` directory is never touched — `verify: python3 tests/smoke.py`
- [x] Repo check passes on 3.10 through 3.13 — `verify: python3 tests/smoke.py` locally, the CI matrix on the PR
- [?] Manual: a photo texted from the phone downloads and opens, and a file sent back arrives — `verify: manual 1. whatsapp-agent recv --json, text a photo from the phone, note the media id 2. whatsapp-agent media get <id> and open the printed path 3. whatsapp-agent send "chart" --file <some png>; it arrives on the phone as a photo with that caption`

## Phases

### Phase 1 — Download
**Status:** Done
- Files: `whatsapp_agent/client.py`, `whatsapp_agent/errors.py`, `tests/smoke.py`
- Change: `WhatsApp.download(media_id, dest_dir)` doing both hops with status checks, mime-prefix extension mapping, and an atomic write (temp file, then rename) so a failure leaves nothing. `media_url_expired` (exit 11) for a 404 on the byte hop; `media_too_large` (exit 10) reserved here and raised in Phase 2.
- Test: fake session covers a good fetch, metadata without a url, a 404 on the second hop, and `audio/ogg; codecs=opus`; the check asserts no partial file survives a failure.

### Phase 2 — Upload
**Status:** Done
- Files: `whatsapp_agent/client.py`, `whatsapp_agent/media.py` (new), `tests/smoke.py`
- Change: `media.py` holds the mime/extension table, the per-type caps and `guess_type`. `WhatsApp.upload(path, mime=None)` checks the cap first, then posts multipart. Both `media_post` and `media_get` keep their own rate-limit windows.
- Test: caps refused before any call; the multipart form carries the documented fields; an unknown extension without `--type` is a usage error.

### Phase 3 — `media` command and `send` attaching
**Status:** Done
- Files: `whatsapp_agent/cli.py`, `tests/smoke.py`
- Change: `media get|put` wired with `--out` and `--keep-hours` and the sweep; `send` gains `--media` and `--file`, `text` becomes optional when either is given, and `WhatsApp.send_media(to, media_id, caption, filename, mime)` posts the image-or-document body. Sent attachments are recorded in the store like any other outgoing message.
- Test: end to end through `cli.main` with a fake session and a temp state dir, both attach paths, the usage error, and the sweep.

### Phase 4 — Checklist and manual pass
**Status:** Done
- Files: `docs/feat-checklist/GH-6-media.md`, `docs/feat-checklist/INDEX.md`
- Change: record what was proven and the manual steps for the phone.
- Test: the repo check, and the CI matrix on the PR.

## Risks

- **A half-written file that looks complete.** Mitigated by writing to a temp name and renaming only after the body is fully written.
- **Sweeping something the caller wanted.** The sweep only ever touches the state directory's own `media/`, never `--out`, and the check asserts that.
- **Caption assumptions.** The platform's caption limit is lower than a text body's and is not chunked here; if the manual pass shows a caption being refused, the fix is to say so with a code, not to split silently.
- **Scope creep into #7.** A voice note downloads like any other media; turning it into text is transcription, and stays refused until #7.

## Out of scope

- Transcription — #7.
- Video and stickers as first-class types: they download like anything else, but nothing special is done for them.
- `recv --download`, fetching bytes automatically as messages arrive. A caller can pipe ids into `media get`; making the poll loop do it would put an unbounded fetch inside the delivery path.

## What actually happened (2026-09-17)

Three phases of code as planned, with two adjustments:

1. **A downloaded path is printed resolved.** `--out ./here` was printing an unresolved path, which on macOS differs from where the file actually is (`/var` versus `/private/var`). The one line `media get` prints is now absolute and canonical, so `open "$(whatsapp-agent media get <id>)"` works from any directory.
2. **A webp is treated as a sticker for its cap, and as a document for its type.** The platform's 500 KB sticker cap only makes sense against webp, and re-encoding someone's webp into an `image` message would lose the filename. Both are one-line rules in `media.py` with the reasoning next to them.

Verified beyond the fake session: an oversize file exits 10 **before any request is made**, an unguessable extension exits 2 asking for `--type`, and a download with a dead token exits 4 against the live endpoint.
