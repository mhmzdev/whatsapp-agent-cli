"""`wa-agent doctor`: say what is wrong with a setup, one line a check.

The rule that shapes it: **checking must not disturb.** A poll from here would take
the long-poll from a running `recv` and hand it a 409, so the token is checked with
`WhatsApp.probe_token` (a read that cannot be a poll), the state directory is looked
at and never written to, and nothing here creates a file. Every line is fixed text
plus the name of a variable or a path; a secret's value, and the text of an exception
that might carry one, never reaches a line.

Each check returns a `Check`. A `FAIL` always carries a fix; an `optional` line is a
feature that is not set up, or could not be verified, and never fails a script.

The two key probes are unconfirmed against the live providers: which statuses mean
"rejected" is what their documentation and the platform's habits suggest, not what
has been observed. An answer the tables do not know is `unverified`, never `accepted`.
"""

import os
import sys
from collections import namedtuple
from pathlib import Path

from .client import WhatsApp
from .errors import AuthError, WhatsAppError
from .state import DEFAULT_PROFILE, TOKEN_ENV, state_dir
from .store import Store
from .transcribe import KEY_ENVS, PROVIDERS, api_key

Check = namedtuple("Check", "name status message fix")

OK, FAIL, OPTIONAL = "ok", "fail", "optional"
MIN_PYTHON = (3, 10)   # kept equal to `requires-python` in pyproject.toml; the check compares them

ACCEPTED, REJECTED, UNVERIFIED = "accepted", "rejected", "unverified"

# One authenticated GET each, metadata only: no generation, no audio, no credits.
# OpenRouter's path is from its documentation ("to check the rate limit or credits
# left on an API key, make a GET request to /api/v1/key"). The status each answers to
# a bad key is unconfirmed for both; see the module docstring.
KEY_PROBES = {
    "gemini": {
        "name": "Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
        "headers": lambda key: {"x-goog-api-key": key},
        "rejected": (400, 401, 403),
    },
    "openrouter": {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/key",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "rejected": (401, 403),
    },
}
assert set(KEY_PROBES) == set(PROVIDERS), "every transcription provider needs a key probe"


def probe_key(provider, key, session=None, timeout=15):
    """`accepted`, `rejected` or `unverified` for one provider's key.

    Anything short of a clear answer — a dropped connection, a 429, a 5xx, a status
    the table does not know — is `unverified`: an optional feature's network blip, or
    an endpoint that moved, must not fail a script, and must not read as a good key.
    """
    probe = KEY_PROBES[provider]
    if session is None:
        import requests

        session = requests.Session()
        transport_errors = (requests.RequestException,)
    else:
        transport_errors = tuple(getattr(session, "transport_errors", ()) or ())
    try:
        response = session.request("GET", probe["url"], headers=probe["headers"](key), timeout=timeout)
    except transport_errors:
        return UNVERIFIED
    status = response.status_code
    if 200 <= status < 300:
        return ACCEPTED
    if status in probe["rejected"]:
        return REJECTED
    return UNVERIFIED


def check_python(python_version=None):
    version = tuple(python_version or sys.version_info[:3])
    shown = ".".join(str(part) for part in version[:3])
    if tuple(version[:2]) >= MIN_PYTHON:
        return Check("python", OK, shown, "")
    need = ".".join(str(part) for part in MIN_PYTHON)
    return Check("python", FAIL, f"{shown} is older than the {need} this needs", f"install Python {need} or newer")


def _token_source(token_file, env):
    """`(token, source)`, or `(None, reason)`. Which source won is worth saying, and
    `resolve_token` does not report it."""
    token = (env.get(TOKEN_ENV) or "").strip()
    if token:
        return token, TOKEN_ENV
    if not token_file:
        return None, f"no token in {TOKEN_ENV} and no --token-file"
    path = Path(token_file).expanduser()
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, f"--token-file {path} cannot be read"
    if not token:
        return None, f"--token-file {path} is empty"
    return token, f"--token-file {path}"


def check_token(token_file=None, env=None, session=None):
    env = os.environ if env is None else env
    token, source = _token_source(token_file, env)
    if token is None:
        return Check("token", FAIL, source,
                     f"export {TOKEN_ENV}, or pass --token-file PATH before the subcommand")
    if any(ch.isspace() for ch in token):
        # A token pasted across two lines: the platform would only ever say 401.
        return Check("token", FAIL, f"the token in {source} contains whitespace inside it",
                     "paste it again as one unbroken line; a trailing newline is fine, a line break inside is not")
    try:
        WhatsApp(token, session=session).probe_token()
    except AuthError:
        return Check("token", FAIL, f"the platform rejected the token in {source}",
                     "get a fresh token: WhatsApp app, Settings, Agents, your agent, API key")
    except WhatsAppError as exc:
        if exc.code == "platform_unavailable":
            return Check("token", FAIL, "could not reach the platform to verify the token",
                         "check the connection and run doctor again; a token that could not be checked is not a good one")
        return Check("token", FAIL, "the platform answered something unexpected, so the token could not be verified",
                     "run doctor again; if it keeps happening, open an issue on the repository")
    return Check("token", OK, f"accepted by the platform (from {source})", "")


def check_key(provider, env=None, session=None):
    env = os.environ if env is None else env
    var = KEY_ENVS[provider]
    label = KEY_PROBES[provider]["name"]
    name = f"{provider} key"
    key = api_key(var, env=env)
    if not key:
        return Check(name, OPTIONAL, f"{var} is not set; only needed for --provider {provider}", "")
    result = probe_key(provider, key, session=session)
    if result == ACCEPTED:
        return Check(name, OK, f"{var} accepted by {label}", "")
    if result == REJECTED:
        return Check(name, FAIL, f"{var} is set, but {label} rejected it",
                     f"put a valid key in {var}, or unset it if you do not use --provider {provider}")
    return Check(name, OPTIONAL, f"{var} is set; {label} could not be reached or gave no clear answer, so it is not verified", "")


def _nearest_existing(path):
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def check_state_dir(profile=DEFAULT_PROFILE, override=None, env=None):
    """Writable, or absent with a writable place to make it. Created and written: never."""
    try:
        path = state_dir(profile, override, env=env, create=False)
    except WhatsAppError:
        return None, Check("state dir", FAIL, "the --profile name is not a single name",
                           "use a plain name such as --profile work, with no slash")
    fix = "make it writable, or point --state-dir somewhere you can write"
    if path.exists():
        if not path.is_dir():
            return path, Check("state dir", FAIL, f"{path} exists and is not a directory", fix)
        if os.access(path, os.W_OK | os.X_OK):
            return path, Check("state dir", OK, f"{path} is writable", "")
        return path, Check("state dir", FAIL, f"{path} is not writable", fix)
    parent = _nearest_existing(path)
    if parent is not None and parent.is_dir() and os.access(parent, os.W_OK | os.X_OK):
        return path, Check("state dir", OK, f"{path} does not exist yet; it will be created on first use", "")
    return path, Check("state dir", FAIL, f"{path} cannot be created: nothing above it is writable", fix)


def check_creator(path):
    fix = "run `wa-agent recv` and message your agent once; until then `send` needs --to"
    if path is None:
        return Check("creator", FAIL, "cannot look: the state directory is not resolved", "fix the state dir line first")
    try:
        creator = Store(path).creator()
    except OSError:
        return Check("creator", FAIL, "the recorded creator cannot be read", "fix the state dir line first")
    if creator:
        return Check("creator", OK, "recorded", "")
    return Check("creator", FAIL, "none recorded yet", fix)


def run_checks(token_file=None, state_dir_override=None, profile=DEFAULT_PROFILE,
               env=None, session=None, python_version=None):
    """Every check, in the order a later one can lean on an earlier one."""
    env = os.environ if env is None else env
    path, state = check_state_dir(profile, state_dir_override, env=env)
    return [
        check_python(python_version),
        check_token(token_file, env=env, session=session),
        *(check_key(provider, env=env, session=session) for provider in PROVIDERS),
        state,
        check_creator(path),
    ]


def failed(checks):
    return [check for check in checks if check.status == FAIL]


def render(checks):
    """The report, one line a check, and a `fix:` line under each failure."""
    label = {OK: "ok", FAIL: "FAIL", OPTIONAL: "optional"}
    width = max(len(check.name) for check in checks)
    lines = []
    for check in checks:
        lines.append(f"{label[check.status]:<10}{check.name:<{width + 2}}{check.message}")
        if check.status == FAIL:
            lines.append(f"{'':<10}fix: {check.fix}")
    return lines
