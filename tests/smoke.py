#!/usr/bin/env python3
"""The repo check: no network, no token, no writes outside a temp directory.

Run it before calling anything done:

    python3 tests/smoke.py

A linear script on purpose — each section prints what it proved, so a failure in
CI reads as a sentence rather than a stack of fixtures. It works from a source
checkout as well as an installed package.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import whatsapp_agent  # noqa: E402
from whatsapp_agent import cli, errors, state  # noqa: E402

FORBIDDEN = ("Traceback", 'HTTP', '{"error"', "OAuthException", "gemini", "openai")


def section(title):
    print(f"\n=== {title}")


def run_cli(argv, env=None):
    """cli.main in-process, returning (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    env = {} if env is None else env
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = cli.main(argv, env=env)
        except SystemExit as exc:  # argparse exits on --help / bad usage
            status = exc.code if isinstance(exc.code, int) else 1
    return status, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- version
section("version")
pyproject = tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]
assert pyproject["name"] == "whatsapp-agent", pyproject["name"]
declared = pyproject["version"]
assert declared.count(".") == 2 and all(p.isdigit() for p in declared.split(".")), declared
installed = whatsapp_agent.__version__
assert installed == declared or installed == "0.0.0+dev", f"{installed} vs {declared}"
status, out, err = run_cli(["--version"])
assert status == 0 and installed in out, (status, out)
print(f"pyproject {declared}; package reports {installed}; --version agrees")

# --------------------------------------------------------------------------- errors
section("errors")
statuses = {}
for code, entry in errors.CODES.items():
    assert entry.message and not entry.message.endswith("."), code
    assert entry.exit_status not in statuses, f"{code} and {statuses[entry.exit_status]} share exit {entry.exit_status}"
    statuses[entry.exit_status] = code
    for bad in FORBIDDEN:
        assert bad.lower() not in entry.message.lower(), f"{code} message leaks {bad!r}"
assert 0 not in statuses, "a failure code may never exit 0"
assert errors.classify(ValueError("boom")) == "internal"
assert errors.classify(errors.WhatsAppError("no_token")) == "no_token"
assert errors.classify(errors.AuthError("401")) == "auth"
assert errors.exit_status("nope") == errors.CODES["internal"].exit_status
try:
    errors.WhatsAppError("made_up_code")
    raise AssertionError("an unregistered code must raise")
except KeyError:
    pass
print(f"{len(errors.CODES)} codes, unique exit statuses {sorted(statuses)}, classify falls back to internal")

# --------------------------------------------------------------------------- token
section("token")
with tempfile.TemporaryDirectory() as tmp:
    token_path = Path(tmp) / "token"
    token_path.write_text("file-token\n")
    assert state.resolve_token(env={state.TOKEN_ENV: "env-token"}) == "env-token"
    assert state.resolve_token(str(token_path), env={state.TOKEN_ENV: "env-token"}) == "env-token"
    assert state.resolve_token(str(token_path), env={}) == "file-token"
    (Path(tmp) / "empty").write_text("   \n")
    for args, why in [((None,), "no env, no file"), ((str(Path(tmp) / "empty"),), "empty file"), ((str(Path(tmp) / "missing"),), "missing file")]:
        try:
            state.resolve_token(*args, env={})
            raise AssertionError(f"expected no_token for {why}")
        except errors.WhatsAppError as exc:
            assert exc.code == "no_token" and exc.exit_status == 3, (why, exc.code)
            assert "file-token" not in str(exc) and "file-token" not in exc.detail, "a token must never reach a message"
print("env wins over file, both stripped; missing, empty and unreadable all exit 3 without echoing a token")

# --------------------------------------------------------------------------- state dir
section("state dir")
with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as home:
    previous = os.getcwd()
    os.chdir(cwd)
    try:
        env = {"HOME": home}
        path = state.state_dir(env=env)
        assert path == Path(home).resolve() / ".local" / "state" / "whatsapp-agent" / "default", path
        assert path.is_dir() and (path.stat().st_mode & 0o777) == 0o700, oct(path.stat().st_mode)
        assert Path(cwd).resolve() not in path.parents, f"{path} is inside the working directory"
        assert state.state_dir(env=env) == path, "resolving twice must not fail on an existing directory"

        xdg = Path(home) / "xdg"
        assert state.state_dir(env={"HOME": home, "XDG_STATE_HOME": str(xdg)}) == (xdg / "whatsapp-agent" / "default").resolve()
        assert state.state_dir(profile="work", env=env).name == "work"
        override = Path(home) / "elsewhere"
        assert state.state_dir(override=str(override), env=env) == override.resolve()
        for bad in ("../escape", "a/b", ".."):
            try:
                state.state_dir(profile=bad, env=env)
                raise AssertionError(f"profile {bad!r} must be refused")
            except errors.WhatsAppError as exc:
                assert exc.code == "bad_usage", exc.code
    finally:
        os.chdir(previous)
print("default lands under HOME, not the working directory; 0700; XDG, profile and override honoured; path-like profiles refused")

# --------------------------------------------------------------------------- cli surface
section("cli surface")
status, out, err = run_cli(["--help"])
assert status == 0, status
for name in ("send", "recv", "media", "transcribe"):
    assert name in out, f"--help does not list {name}"
stubs = [(["send", "hi"], 4), (["recv"], 5), (["recv", "--follow", "--json"], 5), (["media", "get", "abc"], 6), (["media", "put", "f.png"], 6), (["transcribe", "note.ogg"], 7)]
for argv, issue in stubs:
    status, out, err = run_cli(argv)
    assert status == errors.CODES["not_implemented"].exit_status, (argv, status)
    assert f"#{issue}" in err, (argv, err)
    assert "Traceback" not in err, (argv, err)
    assert out == "", (argv, out)
status, out, err = run_cli(["nonsense"])
assert status == 2, status
status, out, err = run_cli([])
assert status == 2, "no subcommand must be a usage error, not a success"
print(f"--help lists every subcommand; {len(stubs)} stubs exit {errors.CODES['not_implemented'].exit_status} naming their issue; bad usage exits 2; no traceback")

# --------------------------------------------------------------------------- module entry point
section("module entry point")
proc = subprocess.run([sys.executable, "-m", "whatsapp_agent", "--version"], capture_output=True, text=True, cwd=ROOT,
                      env={**os.environ, "PYTHONPATH": str(ROOT)})
assert proc.returncode == 0, proc.stderr
assert installed in proc.stdout, proc.stdout
proc = subprocess.run([sys.executable, "-m", "whatsapp_agent", "send", "hi"], capture_output=True, text=True, cwd=ROOT,
                      env={**os.environ, "PYTHONPATH": str(ROOT)})
assert proc.returncode == errors.CODES["not_implemented"].exit_status, proc.returncode
assert "Traceback" not in proc.stderr, proc.stderr
print("python -m whatsapp_agent matches the installed command, including its exit status")

# --------------------------------------------------------------------------- no stray state
section("no stray state")
strays = [
    str(p.relative_to(ROOT))
    for p in ROOT.rglob("*")
    if ".git" not in p.parts
    and (p.name in ("offset", "messages.jsonl", "whatsapp-agent") or p.suffix == ".jsonl")
]
assert not strays, f"the check left state behind: {strays}"
print("no cursor, store or media artifact anywhere in the repo")

print("\nall checks passed")
