"""Failures are codes with exit statuses, never tracebacks.

A caller of this package is a shell script, a cron job or another program, so a
failure has to be something it can branch on. Every failure is a registered code
carrying a fixed one-line message and a unique exit status; the raw detail (an
exception's text, an HTTP body) goes only to `detail`, which is printed when
WHATSAPP_AGENT_DEBUG is set and never otherwise.

Exit statuses, stable from here on — a script may switch on them:

    2   bad_usage             wrong arguments (argparse exits 2 for the same reason)
    3   no_token              no token in the environment and none in --token-file
    4   auth                  the platform rejected the token itself; retrying never helps
    5   not_implemented       a subcommand that exists but has not landed yet
    6   platform_rejected     the platform refused this request; a retry will be refused too
    7   platform_unavailable  the platform or the network was unreachable; a retry may work
    8   no_recipient          no --to given and no creator recorded yet
    9   another_poller        another process is polling this token; only one may
    10  media_too_large       the file is over the platform's cap for its type
    11  media_url_expired     the download url has expired; ask for the media again
    12  no_transcription_key  no key for the transcription provider
    13  transcription_unavailable  the provider was unreachable; a retry may work
    14  transcription_failed  the provider answered but produced no usable transcript
    70  internal              anything unclassified (EX_SOFTWARE)

The 6 / 7 split is the one a caller acts on: 7 is worth looping on, 6 never is.

Every code is also a row in docs/errors.md, which says what to do about it.
Adding a failure is one CODES row plus one documented row. tests/smoke.py fails when a code has no
message, when two codes share an exit status, or when a message leaks a
traceback, an HTTP body or a provider name.
"""

from collections import namedtuple

# retry: True when waiting and trying again can succeed, False when it never can.
# It is the one thing a script author has to get right.
Error = namedtuple("Error", "exit_status message retry")

CODES = {
    "bad_usage": Error(2, "bad usage", False),
    "no_token": Error(3, "no token: set WHATSAPP_AGENT_TOKEN, or pass --token-file PATH", False),
    "auth": Error(4, "the platform rejected this token; it will not become valid on retry", False),
    "not_implemented": Error(5, "this command has not landed yet", False),
    "platform_rejected": Error(6, "the platform refused this request; retrying will not help", False),
    "platform_unavailable": Error(7, "the platform is unreachable right now; retrying may help", True),
    "no_recipient": Error(8, "no recipient: pass --to, or run recv once so the creator is recorded", False),
    "another_poller": Error(9, "another process is polling this token; only one poller is allowed at a time", False),
    "media_too_large": Error(10, "this file is larger than the platform allows for its type", False),
    "media_url_expired": Error(11, "this download link has expired; ask for the media id again", False),
    "no_transcription_key": Error(12, "no transcription key found; the detail line names the variable to set, or pass --key-env NAME", False),
    "transcription_unavailable": Error(13, "the transcription provider is unreachable right now; retrying may help", True),
    "transcription_failed": Error(14, "the transcription provider produced no usable transcript", False),
    "internal": Error(70, "something went wrong on this side", False),
}


class WhatsAppError(Exception):
    """A failure with a registered code. `detail` is for the operator, never for a reply."""

    def __init__(self, code, detail=""):
        if code not in CODES:
            raise KeyError(f"unregistered error code {code!r}")
        self.code = code
        self.detail = str(detail)
        super().__init__(CODES[code].message)

    @property
    def exit_status(self):
        return CODES[self.code].exit_status

    @property
    def message(self):
        return CODES[self.code].message


class AuthError(WhatsAppError):
    """The platform rejected the token itself — HTTP 401 (error.code 190) or an
    invalid-token 400 (error.code 100). Unlike a 429, a 503 or a dropped
    connection, this never becomes valid on retry, so a long-running caller must
    stop rather than spin. Kept here from the first commit because it is a fact
    about the transport, not about whoever is polling."""

    def __init__(self, detail=""):
        super().__init__("auth", detail)


def classify(exc, default="internal"):
    """Map any exception to a registered code. An unforeseen exception type still
    gets a sensible code and never reaches a caller as a traceback."""
    if isinstance(exc, WhatsAppError):
        return exc.code
    if isinstance(exc, (FileNotFoundError, PermissionError, IsADirectoryError)):
        return "no_token" if "token" in str(exc).lower() else default
    if default not in CODES:
        raise KeyError(f"unregistered error code {default!r}")
    return default


def exit_status(code):
    """The exit status for a code, or internal's when the code is unknown."""
    return CODES.get(code, CODES["internal"]).exit_status
