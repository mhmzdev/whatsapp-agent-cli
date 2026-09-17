"""Where the token comes from, and where state lives.

Both answers deliberately have nothing to do with the caller's working
directory. A project folder is something layer B will care about; this package
keeps its cursor, its message store and its downloaded media under the user's
XDG state directory, so a program that reads a folder can never read this
package's memory of what was said.
"""

import os
from pathlib import Path

from .errors import WhatsAppError

TOKEN_ENV = "WHATSAPP_AGENT_TOKEN"
APP_DIR = "whatsapp-agent"
DEFAULT_PROFILE = "default"


def resolve_token(token_file=None, env=None):
    """The token, from the environment first and a file second.

    The environment wins so that a systemd unit or a CI secret does not have to
    be written to disk. Whichever wins is stripped: a token file written with a
    trailing newline is the normal case, not an error.
    """
    env = os.environ if env is None else env
    token = (env.get(TOKEN_ENV) or "").strip()
    if token:
        return token

    if token_file:
        path = Path(token_file).expanduser()
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            # The path is the operator's own; the message stays fixed.
            raise WhatsAppError("no_token", f"{path}: {exc}") from exc
        if token:
            return token
        raise WhatsAppError("no_token", f"{path} is empty")

    raise WhatsAppError("no_token", f"{TOKEN_ENV} unset and no --token-file given")


def state_dir(profile=DEFAULT_PROFILE, override=None, env=None, create=True):
    """The directory this package keeps its state in, created 0700 on first use.

    Resolution: `--state-dir` if given, else `$XDG_STATE_HOME/whatsapp-agent/<profile>`,
    else `~/.local/state/whatsapp-agent/<profile>`. Never derived from the current
    working directory — that is the point of this function, and tests/smoke.py
    asserts it by resolving from a temporary directory.
    """
    env = os.environ if env is None else env

    if override:
        path = Path(override).expanduser()
    else:
        profile = (profile or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
        if "/" in profile or profile in (".", ".."):
            raise WhatsAppError("bad_usage", f"profile {profile!r} is not a single name")
        base = (env.get("XDG_STATE_HOME") or "").strip()
        root = Path(base).expanduser() if base else Path(env.get("HOME", "~")).expanduser() / ".local" / "state"
        path = root / APP_DIR / profile

    path = path.resolve()
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        except OSError as exc:
            raise WhatsAppError("bad_usage", f"{path}: {exc}") from exc
    return path
