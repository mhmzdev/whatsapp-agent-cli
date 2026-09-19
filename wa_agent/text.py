"""Turning what a program wrote into what WhatsApp renders.

Two jobs, both pure: convert the markdown a caller is likely to produce into
WhatsApp's own formatting, and split a long body into parts that fit. The
platform refuses a text over 4,096 characters with a 400, so the default working
limit is lower, leaving room for the `(i/n)` suffix.
"""

import re

MAX_CHARS = 4096          # the platform's hard cap on one text message
DEFAULT_CHUNK = 3500      # what we actually pack, leaving room for "(i/n)"


def to_whatsapp(text):
    """Markdown → WhatsApp formatting, line by line.

    `**bold**` becomes `*bold*`, a heading becomes a bold line, a `-` or `*`
    bullet becomes `•`. Code fences are left alone: WhatsApp renders ``` as
    monospace already.
    """
    out = []
    for line in text.splitlines():
        line = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", line)
        line = re.sub(r"^#{1,6} +(.*)$", r"*\1*", line)
        line = re.sub(r"^\s*[-*] ", "• ", line)
        out.append(line.rstrip())
    return "\n".join(out).strip()


def chunks(text, max_len=DEFAULT_CHUNK):
    """Split on paragraph boundaries into parts of at most `max_len` characters.

    A single paragraph longer than the limit is cut hard — there is nowhere
    better to break it, and dropping the tail would be worse than an ugly seam.
    Always returns at least one part, so a caller never has to special-case an
    empty body.
    """
    if max_len < 1:
        raise ValueError("max_len must be positive")
    parts, buf = [], ""
    for para in text.split("\n\n"):
        while len(para) > max_len:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(para[:max_len])
            para = para[max_len:]
        if not buf:
            buf = para
        elif len(buf) + 2 + len(para) <= max_len:
            buf = f"{buf}\n\n{para}"
        else:
            parts.append(buf)
            buf = para
    if buf:
        parts.append(buf)
    return parts or [""]


def numbered(parts):
    """Append `(i/n)` to each part when there is more than one."""
    if len(parts) < 2:
        return list(parts)
    total = len(parts)
    return [f"{part}\n\n({i}/{total})" for i, part in enumerate(parts, 1)]
