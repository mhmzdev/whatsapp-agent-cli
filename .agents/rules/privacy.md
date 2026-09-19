---
description: The relay is extracted from the author's personal setup. What may come across, and what never does.
paths:
  - "**"
---

# Privacy — generalise or leave it out

The relay began as a script over the author's own notes vault on their own server. Its behaviour is worth carrying; its particulars are not. This rule applies to code, tests, docs, examples, issues, PR bodies and commit messages alike.

## Never

- A server address, hostname or SSH detail.
- A token, a token file path from the author's machine, or any key name offered as the default (a provider's key is named by the user's config, not by us).
- The author's WhatsApp creator id, phone number, or any real `user:` id.
- Folder names, file names or skill names from the author's vault, or anything describing what that vault contains.
- Dates, anecdotes or journal lines that identify the personal setup beyond "a personal relay has run since September 2026".

## Always

- Example configs name a **fake project** (a made-up folder, made-up write paths).
- A comment that explains *why* a behaviour exists keeps the lesson and drops the setting: "plain `-p` prints only the final message, so a reply that answered and then wrote a file lost its answer" is fine; which skill and which file it was is not.
- When in doubt, generalise or leave it out. Ask before committing anything you are unsure of.

## Before every commit

Read the staged diff (`git diff --cached`) for the items above. Stage by name; never `git add -A`.
