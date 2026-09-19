---
type: FeatChecklist
slug: GH-7-transcribe
issue: 7
timestamp: 2026-09-18T00:00:00Z
---

# GH-7-transcribe — acceptance checklist   (11 proven · 1 manual · 0 failing)

- [x] `whatsapp-agent transcribe note.ogg` prints the transcript and nothing else — proven in the check, and **live**: a synthesized voice note came back in 3.6s with "meeting at 4" rendered as a digit, as the prompt asks
- [x] The request carries the audio inline with its mime type, the key in a header (never in the url), and the prompt — asserted field by field, including that the base64 decodes to the original bytes
- [x] `recv --transcribe` adds `text.body` and `transcribed: true` while leaving `type` and the audio object untouched — a typed message in the same batch is untouched
- [x] The fetched audio is deleted either way and never reaches the media directory — the check globs the whole state directory for `.ogg` afterwards
- [x] A failed transcription still delivers the message marked `transcribed: false` with the code, warns, and `--follow` keeps going — the cursor still advances
- [x] A failure never invents words: a marked message carries no `text` at all
- [x] No key exits 12 naming the variable — proven in the check and live with the key unset
- [x] Unreachable (13) and unusable (14) are separate, and only 13 is retryable — seven failure modes, including a 200 carrying a refusal rather than a transcript
- [x] The store records the transcript, not `<audio …>`, so a quoted-reply lookup returns words
- [x] Each billed call prints one stderr line naming the message id
- [x] The default install needs no extra: `pyproject.toml` declares only `dev`, and the README check now fails if the prose offers an extra that does not exist
- [?] A real voice note from the phone — needs a message from the handset; a live listener is running against the demo agent for exactly this

## Conventions

- **Failures are codes** — three new ones, each documented with what to do, and the retryable set is now pinned explicitly so a new code cannot quietly claim a caller should loop on it.
- **No key material in any message or detail** — asserted for every failure mode.
- **Layer purity** — transcription is bytes in, words out. What anyone does with the words is their business.

## Findings

**FINDING-10 · Minor · `whatsapp_agent/transcribe.py`** — the whole audio file is base64'd into memory and into one request. Fine for voice notes (tens of kilobytes) and bounded by the platform's own 16 MB media cap, but a long attached audio file would mean a large request body. If that ever matters, Gemini's resumable upload endpoint is the fix.

**FINDING-11 · Minor · the check** — `transcription_failed` covers both "the provider refused" and "the audio was unintelligible". A caller cannot tell a safety refusal from a bad recording without reading the detail line. Splitting them would need Gemini's own reason codes, which it does not always send.
