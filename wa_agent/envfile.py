"""`./.env`, read by the command-line tool and never by the library.

Every command fills gaps in the environment from a `.env` file in the directory it
runs in. The shell always wins, and nothing here writes to `os.environ`: `merge`
returns a new mapping, which the CLI hands down the way it already hands down the
environment. A program that imports `wa_agent` never reads a file from its working
directory because of this module, since only `cli.main` calls it.

No dependency for this. The format is the small, common subset: `KEY=VALUE`, `#`
comments, blank lines, an optional `export `, and single or double quotes taken
literally (no escapes, no `$` interpolation, no value spanning lines). A line that
is none of those is skipped and reported by its number. The line itself is never
repeated anywhere, because it may hold a secret.
"""

import re
from pathlib import Path

FILENAME = ".env"
SHOWN = "./.env"   # how the file is named in every message: the same wherever it is

SHELL, DOTENV, SHADOWED = "shell", "dotenv", "shadowed"
# Set only in ./.env, and not used because a flag took precedence (the CLI's --token-file).
OVERRIDDEN = "overridden"

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _value(rest):
    """The value from what follows `=`, or None when the line is malformed."""
    rest = rest.strip()
    if rest[:1] in ("'", '"'):
        close = rest.find(rest[0], 1)
        if close < 0:
            return None
        after = rest[close + 1:].strip()
        if after and not after.startswith("#"):
            return None
        return rest[1:close]
    # an unquoted value ends at a comment, and only a comment set off by whitespace:
    # `a#b` is a value, `a #b` is `a` and a comment
    match = re.search(r"\s#", rest)
    return (rest[:match.start()] if match else rest).strip()


def parse(text):
    """`(values, skipped)`: the variables a file sets, and the 1-based numbers of the
    lines that could not be read. A variable whose value is blank sets nothing, so a
    `.env` copied from `.env.example` and never filled in contributes nothing."""
    values, skipped = {}, []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export"):].lstrip()
        key, sep, rest = line.partition("=")
        key = key.strip()
        value = _value(rest) if sep else None
        if value is None or not _KEY.fullmatch(key):
            skipped.append(number)
            continue
        if value.strip():
            values[key] = value
        else:
            values.pop(key, None)   # a later blank line undoes an earlier value, as `source` would
    return values, skipped


def load(directory):
    """`(values, skipped, problem)` for `directory/.env`. No file is `({}, [], None)`.
    A file that cannot be read is `({}, [], reason)`: the caller warns, and carries on
    with the shell alone rather than failing a command over an optional file."""
    path = Path(directory) / FILENAME
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, [], None
    except OSError:
        return {}, [], "cannot be read"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {}, [], "is not UTF-8"
    values, skipped = parse(text)
    return values, skipped, None


def describe(name, source, inner=False):
    """Where a variable came from, in the words every message uses. `inner` is for a
    phrase that already sits inside parentheses, so a shadowed one does not nest."""
    if source == DOTENV:
        return f"{name} from {SHOWN}"
    if source == SHADOWED:
        also = f"{SHOWN} also sets it, not used"
        return f"{name} from the shell; {also}" if inner else f"{name} from the shell ({also})"
    if source == OVERRIDDEN:
        return f"{name} from {SHOWN}, not used (--token-file given)"
    return f"{name} from the shell"


def _set(value):
    return bool((value or "").strip())


def merge(shell, values):
    """`(merged, sources)`. `merged` is a new dict: the shell, with every gap `values`
    can fill filled. A shell variable counts as set only when it is not blank, the
    same test every reader in the package applies, so an empty export does not hide
    the file's value behind a run that then says the variable is missing.

    `sources` maps each name set in either place to `SHELL`, `DOTENV`, or `SHADOWED`
    (both set it; the shell's value was used)."""
    merged = dict(shell)
    sources = {}
    for name, value in shell.items():
        if _set(value):
            sources[name] = SHELL
    for name, value in values.items():
        if name in sources:
            sources[name] = SHADOWED
        else:
            merged[name] = value
            sources[name] = DOTENV
    return merged, sources
