"""What the platform will carry, and under what size.

Two facts live here, both from the platform manual, and both easy to get wrong
elsewhere: a mime type arrives with parameters attached (`audio/ogg;
codecs=opus`), so it is matched on its prefix; and the size cap depends on the
kind of file, not on one global number.
"""

import mimetypes
from pathlib import Path

# Prefix → extension. Ordered longest-prefix-first is unnecessary: no prefix here
# is a prefix of another.
EXTENSIONS = (
    ("image/jpeg", ".jpg"),
    ("image/png", ".png"),
    ("image/webp", ".webp"),
    ("image/gif", ".gif"),
    ("audio/ogg", ".ogg"),
    ("audio/mp4", ".m4a"),
    ("audio/aac", ".aac"),
    ("audio/mpeg", ".mp3"),
    ("audio/amr", ".amr"),
    ("video/mp4", ".mp4"),
    ("video/3gpp", ".3gp"),
    ("application/pdf", ".pdf"),
    ("text/plain", ".txt"),
)

MB = 1024 * 1024
# Manual: 5 MB image, 500 KB sticker, 16 MB video / audio / document / generic binary.
CAPS = (
    ("image/webp", 500 * 1024),   # a webp is how a sticker arrives; the tighter cap wins
    ("image/", 5 * MB),
    ("", 16 * MB),                # everything else
)
GENERIC = "application/octet-stream"


def extension_for(mime):
    """The file extension for a mime type, matched on the prefix. Empty when unknown."""
    value = (mime or "").lower().strip()
    for prefix, ext in EXTENSIONS:
        if value.startswith(prefix):
            return ext
    return ""


def cap_for(mime):
    """The platform's size limit in bytes for this type."""
    value = (mime or "").lower().strip()
    for prefix, cap in CAPS:
        if value.startswith(prefix):
            return cap
    return CAPS[-1][1]


def guess_type(path):
    """The mime type for a local file, from its extension. None when unknown — the
    caller then needs `--type`, because guessing `application/octet-stream` would
    send a photo as a nameless blob."""
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed


def kind_for(mime):
    """Which message type carries this file: an image, or a document.

    The platform also has audio, video and sticker types; a document is the honest
    default for everything that is not obviously a photo, because it keeps the
    filename and never gets re-encoded.
    """
    return "image" if (mime or "").lower().startswith("image/") and not (mime or "").lower().startswith("image/webp") else "document"


def describe(path):
    """`(mime, size)` for a local file, without reading it."""
    path = Path(path)
    return guess_type(path), path.stat().st_size
