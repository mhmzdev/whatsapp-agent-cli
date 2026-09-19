#!/usr/bin/env python3
"""The repo check: no network, no token, no writes outside a temp directory.

Run it before calling anything done:

    python3 tests/smoke.py

A linear script on purpose — each section prints what it proved, so a failure in
CI reads as a sentence rather than a stack of fixtures. It works from a source
checkout as well as an installed package.
"""

import base64
import contextlib
import importlib.machinery
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wa_agent  # noqa: E402
from wa_agent import cli, client, doctor, errors, local, media, ratelimit, state, store, text, transcribe  # noqa: E402

# What must never reach a user's terminal: our internals, or a provider's raw words.
# Provider *names* are deliberately allowed here, unlike in hisab: a developer who has
# to set GEMINI_API_KEY needs to be told which variable, and hiding the name to keep a
# rule that was written for a ledger's end user would make the message useless.
FORBIDDEN = ("Traceback", "HTTP", '{"error"', "OAuthException", "fbtrace")


def section(title):
    print(f"\n=== {title}")


def project_fields_regex(text):
    """name and version out of pyproject.toml without a TOML parser.

    tomllib arrived in 3.11 and the package supports 3.10, so the check cannot
    depend on it. Only these two fields are ever read here, and both are plain
    strings at the top of [project]. Where tomllib does exist, the version
    section below asserts this parser agrees with it.
    """
    body = text.split("[project]", 1)[1].split("\n[", 1)[0]
    found = {}
    for key in ("name", "version"):
        match = re.search(rf'^{key}\s*=\s*"([^"]+)"', body, re.MULTILINE)
        assert match, f"no {key} in [project]"
        found[key] = match.group(1)
    return found


def run_cli(argv, env=None, session=None, sleep=None):
    """cli.main in-process, returning (exit status, stdout, stderr).

    `sleep` stands in for time.sleep so backoff is provable without waiting."""
    out, err = io.StringIO(), io.StringIO()
    env = {} if env is None else env
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = cli.main(argv, env=env, session=session, sleep=sleep)
        except SystemExit as exc:  # argparse exits on --help / bad usage
            status = exc.code if isinstance(exc.code, int) else 1
    return status, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- version
section("version")
raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
pyproject = project_fields_regex(raw)
project_extras = re.findall(r"^([a-z]+)\s*=\s*\[", raw.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0], re.MULTILINE) if "[project.optional-dependencies]" in raw else []
try:
    import tomllib  # 3.11+
except ModuleNotFoundError:
    parsed_by = "regex (no tomllib before 3.11)"
else:
    real = tomllib.loads(raw)["project"]
    assert {k: real[k] for k in pyproject} == pyproject, f"{pyproject} disagrees with tomllib {real}"
    parsed_by = "regex, agreeing with tomllib"
assert pyproject["name"] == "wa-agent", pyproject["name"]
declared = pyproject["version"]
assert declared.count(".") == 2 and all(p.isdigit() for p in declared.split(".")), declared
installed = wa_agent.__version__
assert installed == declared or installed == "0.0.0+dev", f"{installed} vs {declared}"
status, out, err = run_cli(["--version"])
assert status == 0 and installed in out, (status, out)
print(f"pyproject {declared} via {parsed_by}; package reports {installed}; --version agrees")

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
        assert path == Path(home).resolve() / ".local" / "state" / "wa-agent" / "default", path
        assert path.is_dir() and (path.stat().st_mode & 0o777) == 0o700, oct(path.stat().st_mode)
        assert Path(cwd).resolve() not in path.parents, f"{path} is inside the working directory"
        assert state.state_dir(env=env) == path, "resolving twice must not fail on an existing directory"

        xdg = Path(home) / "xdg"
        assert state.state_dir(env={"HOME": home, "XDG_STATE_HOME": str(xdg)}) == (xdg / "wa-agent" / "default").resolve()
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
for name in ("send", "recv", "media", "transcribe", "doctor"):
    assert name in out, f"--help does not list {name}"
# every subcommand is implemented now; not_implemented stays registered for the next one
assert "not_implemented" in errors.CODES
status, out, err = run_cli(["nonsense"])
assert status == 2, status
status, out, err = run_cli([])
assert status == 2, "no subcommand must be a usage error, not a success"
print("--help lists every subcommand; bad usage exits 2; no subcommand exits 2; no traceback")

# --------------------------------------------------------------------------- rate limiter
section("rate limiter")


class FakeClock:
    """A clock that only moves when something sleeps."""

    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        assert seconds >= 0, seconds
        self.t += seconds


clock = FakeClock()
limiter = ratelimit.RateLimiter({"messages": 12}, now=clock.now, sleep=clock.sleep)
start = clock.t
for _ in range(30):
    limiter.acquire("messages")
elapsed = clock.t - start
assert 110 <= elapsed <= 130, f"30 sends at 12/min should span two windows, spanned {elapsed}"
assert limiter.acquire("unknown-method") is None, "an unlimited method never blocks"

clock2 = FakeClock()
limiter2 = ratelimit.RateLimiter({"messages": 12}, now=clock2.now, sleep=clock2.sleep)
limiter2.acquire("messages")
limiter2.penalize("messages")
before = clock2.t
limiter2.acquire("messages")
assert clock2.t - before >= 59, f"penalize must back off toward a window reset, waited {clock2.t - before}"
print(f"30 calls at 12/min paced over {elapsed:.0f}s of simulated time; penalize backs off {clock2.t - before:.0f}s")

# --------------------------------------------------------------------------- text
section("text")
assert text.to_whatsapp("**bold**") == "*bold*"
assert text.to_whatsapp("# Heading") == "*Heading*"
assert text.to_whatsapp("- one\n* two") == "• one\n• two"
assert text.to_whatsapp("  spaced   ") == "spaced"
assert text.chunks("") == [""], "an empty body is still one part"
assert text.chunks("a\n\nb", 10) == ["a\n\nb"]
assert text.chunks("a" * 25, 10) == ["a" * 10, "a" * 10, "a" * 5], "an over-long paragraph is cut hard"
packed = text.chunks("x" * 8 + "\n\n" + "y" * 8, 10)
assert packed == ["x" * 8, "y" * 8], packed
one = text.numbered(["only"])
assert one == ["only"], "a single part is never numbered"
two = text.numbered(["a", "b"])
assert two[0].endswith("(1/2)") and two[1].endswith("(2/2)"), two
assert all(len(p) <= text.DEFAULT_CHUNK + 10 for p in text.numbered(text.chunks("z" * 9000))), "parts stay under the cap"
print("markdown converts; splits on blank lines; hard-cuts a long paragraph; numbers only when split")


# --------------------------------------------------------------------------- client
section("client")


class FakeResponse:
    def __init__(self, status_code, payload=None, body_text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = body_text if body_text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeTransportError(Exception):
    pass


class FakeSession:
    """Returns scripted responses and records what it was asked to send."""

    transport_errors = (FakeTransportError,)

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, verb, url, headers=None, **kwargs):
        self.calls.append({"verb": verb, "url": url, "headers": headers, **kwargs})
        nxt = self.responses.pop(0) if self.responses else FakeResponse(200, {"messages": [{"id": "wamid.default"}]})
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def make_client(responses, **kwargs):
    clk = FakeClock()
    session = FakeSession(responses)
    return client.WhatsApp("secret-token", session=session, now=clk.now, sleep=clk.sleep, **kwargs), session


ok = FakeResponse(200, {"messages": [{"id": "wamid.111"}]})
wa, session = make_client([ok])
sent = wa.send("user:42", "**hello**")
assert [s.id for s in sent] == ["wamid.111"], sent
call = session.calls[0]
assert call["verb"] == "POST" and call["url"].endswith("/messages"), call
assert call["json"] == {"messaging_product": "whatsapp", "to": "user:42", "type": "text", "text": {"body": "*hello*"}}, call["json"]
assert call["headers"]["Authorization"] == "Bearer secret-token"

wa, session = make_client([ok, ok, ok])
sent = wa.send("user:42", "p" * 4000 + "\n\n" + "q" * 4000)
assert len(session.calls) == len(sent) >= 2, (len(session.calls), len(sent))
assert all("(" in s.text.splitlines()[-1] for s in sent), "every part of a split message is numbered"

failures = [
    ([FakeResponse(401, {"error": {"code": 190}})], "auth", 4),
    ([FakeResponse(400, {"error": {"code": 100}})], "auth", 4),
    ([FakeResponse(400, {"error": {"code": 131009}})], "platform_rejected", 6),
    ([FakeResponse(403, {"error": {"code": 131005}})], "platform_rejected", 6),
    ([FakeResponse(500, None, "upstream exploded")], "platform_unavailable", 7),
    ([FakeResponse(503, {"error": {"code": 131016}})], "platform_unavailable", 7),
    ([FakeTransportError("connection reset")], "platform_unavailable", 7),
    ([FakeResponse(429), FakeResponse(429)], "platform_unavailable", 7),
]
for responses, want_code, want_status in failures:
    wa, session = make_client(responses)
    try:
        wa.send("user:42", "hi")
        raise AssertionError(f"expected {want_code}")
    except errors.WhatsAppError as exc:
        assert exc.code == want_code, (want_code, exc.code)
        assert exc.exit_status == want_status, (want_code, exc.exit_status)
        assert "secret-token" not in str(exc) and "secret-token" not in exc.detail, "a token must never reach an error"
        assert "Traceback" not in exc.message
assert isinstance(errors.AuthError(""), errors.WhatsAppError), "AuthError must classify as a WhatsAppError"

wa, session = make_client([FakeResponse(429), ok])
assert [s.id for s in wa.send("user:42", "hi")] == ["wamid.111"], "a 429 is retried once and succeeds"
assert len(session.calls) == 2, session.calls

wa, _ = make_client([FakeResponse(200, None, "not json at all")])
assert wa.send("user:42", "hi")[0].id.startswith("out:"), "a 2xx without a parseable id still yields a key"
print(f"request shape matches the manual; {len(failures)} failure modes map to 4/6/7; 429 retries once; no token in any error")

# --------------------------------------------------------------------------- store
section("store")
with tempfile.TemporaryDirectory() as tmp:
    st = store.Store(tmp)
    assert st.all() == [] and st.lookup("nope") is None and st.creator() is None
    st.add("wamid.1", "out", "first")
    st.add("wamid.2", "in", "second")
    assert st.lookup("wamid.1") == "first" and st.seen("wamid.2") and not st.seen("wamid.3")
    assert store.Store(tmp).lookup("wamid.2") == "second", "a second Store sees the same file"
    assert st.set_creator("user:7") and store.Store(tmp).creator() == "user:7"
    try:
        st.add("wamid.4", "sideways", "x")
        raise AssertionError("an unknown direction must raise")
    except ValueError:
        pass
    with (Path(tmp) / store.MESSAGES).open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    assert len(st.all()) == 2, f"a truncated line is skipped, not fatal: {st.all()}"
    st.add("wamid.3", "out", "third")
    old = store.Store(tmp, now=lambda: time.time() + 40 * 86400)
    assert old.prune() == 3 and old.all() == [], "records older than keep_days are dropped"
    st.add("wamid.5", "out", "after prune")
    assert len(store.Store(tmp).all()) == 1, "the pruned file is still appendable"
    assert set(os.listdir(tmp)) <= {store.MESSAGES, store.CREATOR}, os.listdir(tmp)
print("records round-trip across instances; a corrupt line is skipped; prune drops what is older than 30 days")

# --------------------------------------------------------------------------- send end to end
section("send end to end")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token"}
    sdir = str(Path(home) / "state")
    session = FakeSession([FakeResponse(200, {"messages": [{"id": "wamid.e2e"}]})])
    status, out, err = run_cli(["--state-dir", sdir, "send", "hello", "--to", "user:9"], env=env, session=session)
    assert status == 0, (status, err)
    assert out.strip() == "wamid.e2e", out
    assert store.Store(sdir).lookup("wamid.e2e") == "hello", "the sent text is recorded under its id"

    status, out, err = run_cli(["--state-dir", sdir, "send", "hello"], env=env, session=FakeSession([]))
    assert status == errors.CODES["no_recipient"].exit_status, (status, err)
    store.Store(sdir).set_creator("user:9")
    status, out, err = run_cli(["--state-dir", sdir, "send", "hello"], env=env,
                               session=FakeSession([FakeResponse(200, {"messages": [{"id": "wamid.creator"}]})]))
    assert status == 0 and out.strip() == "wamid.creator", (status, out, err)

    dry = FakeSession([])
    status, out, err = run_cli(["--state-dir", sdir, "send", "# Title\n\nbody", "--to", "user:9", "--dry-run"], env={"HOME": home}, session=dry)
    assert status == 0 and "*Title*" in out and dry.calls == [], (out, dry.calls)
    assert "wamid" not in out, "a dry run invents no ids"

    status, out, err = run_cli(["--state-dir", sdir, "send", "hi", "--to", "user:9"], env={"HOME": home}, session=FakeSession([]))
    assert status == errors.CODES["no_token"].exit_status, (status, err)
    assert "secret-token" not in err
print("send posts, prints and records; --to falls back to the creator; --dry-run touches nothing; no token exits 3")

# --------------------------------------------------------------------------- poll
section("poll")


def envelope(*messages, next_offset="off-2"):
    return FakeResponse(200, {"entry": [{"changes": [{"value": {"messages": list(messages)}}]}],
                              "next_offset": next_offset})


def msg(msg_id, body="hi", sender="user:9", kind="text", **extra):
    out = {"id": msg_id, "from": sender, "type": kind, "timestamp": 1700000000}
    if kind == "text":
        out["text"] = {"body": body}
    else:
        out[kind] = {"id": f"media-{msg_id}", **extra}
    return out


wa, session = make_client([envelope(msg("wamid.A"), msg("wamid.B"))])
messages, next_offset = wa.poll()
assert [m["id"] for m in messages] == ["wamid.A", "wamid.B"], messages
assert next_offset == "off-2", next_offset
params = session.calls[0]["params"]
assert "offset" not in params, f"a first run asks for new traffic only: {params}"
assert params["limit"] == 50 and params["timeout"] == 20, params

wa, session = make_client([envelope()])
wa.poll("off-1")
assert session.calls[0]["params"]["offset"] == "off-1", "a resumed run passes its cursor back unchanged"

wa, session = make_client([envelope()])
wa.poll(None, replay=True)
assert session.calls[0]["params"]["offset"] == 0, "--replay asks for the backlog"

wa, session = make_client([envelope()])
wa.poll(None, timeout=90)
assert session.calls[0]["params"]["timeout"] == client.MAX_POLL_TIMEOUT, "the platform's own ceiling is respected"

wa, _ = make_client([FakeResponse(204, None, "")])
assert wa.poll("off-7") == ([], "off-7"), "a 204 is an empty batch that keeps the cursor"
wa, _ = make_client([FakeResponse(200, {})])
assert wa.poll("off-7") == ([], "off-7"), "no entry key is an empty batch"

wa, _ = make_client([FakeResponse(409, {"error": {"code": 1752041}})])
try:
    wa.poll()
    raise AssertionError("409 must raise")
except errors.WhatsAppError as exc:
    assert exc.code == "another_poller" and exc.exit_status == 9, exc.code

wa, session = make_client([FakeResponse(200, {})])
assert wa.typing("wamid.A") is True
body = session.calls[0]["json"]
assert body == {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.A",
                "typing_indicator": {"type": "text"}}, body
wa, _ = make_client([FakeResponse(500, None, "boom")])
assert wa.typing("wamid.A") is False, "a failed receipt is cosmetic and never raises"
print("first run omits the offset, a resume passes it back, --replay asks 0; 204 and empty envelopes are empty batches; 409 raises; typing never raises")

# --------------------------------------------------------------------------- recv
section("recv")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token"}
    sdir = str(Path(home) / "state")
    base = ["--state-dir", sdir, "recv"]

    session = FakeSession([envelope(msg("wamid.A", "first"), msg("wamid.B", "second"))])
    status, out, err = run_cli(base + ["--json"], env=env, session=session)
    assert status == 0, (status, err)
    lines = [json.loads(line) for line in out.strip().splitlines()]
    assert [m["id"] for m in lines] == ["wamid.A", "wamid.B"], lines
    st = store.Store(sdir)
    assert st.offset() == "off-2", "the cursor advances once the batch is delivered"
    assert st.lookup("wamid.A") == "first" and st.seen("wamid.B")
    assert st.creator() == "user:9", "the creator is recorded from an inbound message"

    session = FakeSession([envelope(msg("wamid.A", "first"), msg("wamid.B", "second"), next_offset="off-3")])
    status, out, err = run_cli(base + ["--json"], env=env, session=session)
    assert status == 0 and out.strip() == "", f"a redelivered batch prints nothing: {out!r}"
    assert store.Store(sdir).offset() == "off-3"

    status, out, err = run_cli(base, env=env, session=FakeSession([envelope(msg("wamid.C", "human please"))]))
    assert "human please" in out and "user:9" in out and "{" not in out, out

    photo = msg("wamid.D", kind="image", caption="the whiteboard")
    status, out, err = run_cli(base, env=env, session=FakeSession([envelope(photo)]))
    assert "<image media-wamid.D>" in out and "the whiteboard" in out, out
    assert store.Store(sdir).lookup("wamid.D").startswith("<image"), "media records a placeholder, not bytes"

    # send now works without --to, because recv recorded the creator
    status, out, err = run_cli(["--state-dir", sdir, "send", "got it"], env=env,
                               session=FakeSession([FakeResponse(200, {"messages": [{"id": "wamid.reply"}]})]))
    assert status == 0 and out.strip() == "wamid.reply", (status, out, err)

    # --typing posts a receipt per delivered message; without it, nothing does
    session = FakeSession([envelope(msg("wamid.E")), FakeResponse(200, {})])
    run_cli(base + ["--typing"], env=env, session=session)
    assert any(c["url"].endswith("/statuses") for c in session.calls), session.calls
    session = FakeSession([envelope(msg("wamid.F"))])
    run_cli(base, env=env, session=session)
    assert not any(c["url"].endswith("/statuses") for c in session.calls), "no receipt without --typing"

    # --transcribe with no key warns rather than refusing; the section below proves the rest
    status, out, err = run_cli(base + ["--transcribe"], env=env, session=FakeSession([envelope()]))
    assert status == 0 and "GEMINI_API_KEY is not set" in err, (status, err)

    for responses, want in [([FakeResponse(401, {"error": {"code": 190}})], 4),
                            ([FakeResponse(409, {"error": {"code": 1752041}})], 9),
                            ([FakeResponse(503, {"error": {"code": 131016}})] * 2, 7)]:
        status, out, err = run_cli(base, env=env, session=FakeSession(responses))
        assert status == want, (want, status, err)
        assert "Traceback" not in err
print("json and human output; dedup silences a redelivered batch; creator recorded then used by send; --typing posts receipts; 401/409/503 exit 4/9/7")

# --------------------------------------------------------------------------- recv: crash window and follow
section("recv: crash window and follow")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token"}
    sdir = str(Path(home) / "state")

    class FailingStore(store.Store):
        """Dies while recording the second message, the way a kill would."""

        def add(self, msg_id, direction, text=""):
            if msg_id == "wamid.two":
                raise KeyboardInterrupt("killed mid-batch")
            return super().add(msg_id, direction, text)

    original = cli.Store
    cli.Store = FailingStore
    try:
        session = FakeSession([envelope(msg("wamid.one"), msg("wamid.two"))])
        status, out, err = run_cli(["--state-dir", sdir, "recv", "--json"], env=env, session=session)
    finally:
        cli.Store = original
    assert status == 130, status
    assert store.Store(sdir).offset() is None, "a batch that did not finish must not move the cursor"
    assert store.Store(sdir).seen("wamid.one") and not store.Store(sdir).seen("wamid.two")
    assert "wamid.two" in out, "the message was printed before it was recorded — it repeats rather than vanishing"

    # the same batch on the next run redelivers only what was not recorded
    session = FakeSession([envelope(msg("wamid.one"), msg("wamid.two"))])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json"], env=env, session=session)
    assert [json.loads(line)["id"] for line in out.strip().splitlines()] == ["wamid.two"], out

    # follow: two 503s back off 1s then 2s, then the batch arrives
    slept = []
    session = FakeSession([FakeResponse(503), FakeResponse(503),
                           envelope(msg("wamid.later"), next_offset="off-9")])

    class StopAfterBatch(store.Store):
        def set_offset(self, value):
            super().set_offset(value)
            raise KeyboardInterrupt("user pressed ctrl-c")

    cli.Store = StopAfterBatch
    try:
        status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--follow"], env=env,
                                   session=session, sleep=slept.append)
    finally:
        cli.Store = original
    assert status == 130, status
    assert slept == [1, 2], f"backoff doubles from 1s: {slept}"
    assert "wamid.later" in out and store.Store(sdir).offset() == "off-9"
    assert err.count("retrying in") == 2 and "unreachable" in err, err
print("a kill mid-batch repeats rather than loses; follow backs off 1s then 2s and recovers; ctrl-c exits 130 with the cursor at the last complete batch")

# --------------------------------------------------------------------------- media types
section("media types")
assert media.extension_for("audio/ogg; codecs=opus") == ".ogg", "a mime type arrives with parameters attached"
assert media.extension_for("image/jpeg") == ".jpg" and media.extension_for("application/pdf") == ".pdf"
assert media.extension_for("application/x-unknown") == "", "an unknown type gets no extension, not a wrong one"
assert media.cap_for("image/png") == 5 * media.MB
assert media.cap_for("image/webp") == 500 * 1024, "a sticker's cap is tighter than an image's"
assert media.cap_for("application/pdf") == 16 * media.MB and media.cap_for("anything/else") == 16 * media.MB
assert media.kind_for("image/png") == "image" and media.kind_for("application/pdf") == "document"
assert media.kind_for("image/webp") == "document", "a webp keeps its filename rather than being re-encoded"
assert media.guess_type("x.png") == "image/png" and media.guess_type("x.unheardof") is None
print("prefix matching survives codec parameters; caps differ by type; images attach as images, everything else as documents")

# --------------------------------------------------------------------------- media transfer
section("media transfer")


class FakeBytes(FakeResponse):
    def __init__(self, status_code, content=b"", ):
        super().__init__(status_code, None, "")
        self.content = content


with tempfile.TemporaryDirectory() as tmp:
    meta = FakeResponse(200, {"url": "https://lookaside.example/abc", "mime_type": "audio/ogg; codecs=opus"})
    wa, session = make_client([meta, FakeBytes(200, b"OggS-fake-bytes")])
    path, mime = wa.download("media-1", tmp)
    assert path.name == "media-1.ogg" and path.read_bytes() == b"OggS-fake-bytes", path
    assert session.calls[0]["url"].endswith("/media/media-1")
    assert session.calls[1]["url"] == "https://lookaside.example/abc"
    assert session.calls[1]["headers"]["Authorization"] == "Bearer secret-token", "the byte hop carries the token too"
    assert not list(Path(tmp).glob("*.part")), "no temp file survives a good download"

    wa, _ = make_client([FakeResponse(200, {"mime_type": "image/png"})])
    for responses, want in [
        ([FakeResponse(200, {"mime_type": "image/png"})], "platform_rejected"),          # metadata with no url
        ([meta, FakeBytes(404)], "media_url_expired"),
        ([meta, FakeBytes(500)], "platform_unavailable"),
        ([FakeResponse(401, {"error": {"code": 190}})], "auth"),
    ]:
        wa, _ = make_client(list(responses))
        try:
            wa.download("media-x", tmp)
            raise AssertionError(f"expected {want}")
        except errors.WhatsAppError as exc:
            assert exc.code == want, (want, exc.code)
    assert not list(Path(tmp).glob("media-x*")), "a failed download leaves nothing behind"

    photo = Path(tmp) / "chart.png"
    photo.write_bytes(b"\x89PNG" + b"0" * 2048)
    wa, session = make_client([FakeResponse(200, {"id": "media-up"})])
    assert wa.upload(photo) == "media-up"
    form = session.calls[0]
    assert form["data"] == {"messaging_product": "whatsapp", "type": "image/png"}, form["data"]
    assert form["files"]["file"][0] == "chart.png" and form["files"]["file"][2] == "image/png"

    big = Path(tmp) / "huge.png"
    big.write_bytes(b"0" * (6 * media.MB))
    wa, session = make_client([FakeResponse(200, {"id": "never"})])
    try:
        wa.upload(big)
        raise AssertionError("expected media_too_large")
    except errors.WhatsAppError as exc:
        assert exc.code == "media_too_large" and exc.exit_status == 10, exc.code
    assert session.calls == [], "the cap is checked before a request is spent"

    odd = Path(tmp) / "thing.unheardof"
    odd.write_bytes(b"x")
    wa, _ = make_client([])
    try:
        wa.upload(odd)
        raise AssertionError("an unguessable type must ask for --type")
    except errors.WhatsAppError as exc:
        assert exc.code == "bad_usage", exc.code
    wa, _ = make_client([FakeResponse(200, {"id": "media-generic"})])
    assert wa.upload(odd, "application/octet-stream") == "media-generic", "an explicit --type unblocks an unguessable file"

    wa, session = make_client([FakeResponse(200, {"messages": [{"id": "wamid.att"}]})])
    sent = wa.send_media("user:9", "media-up", caption="**look**", filename="chart.png", mime="image/png")
    body = session.calls[0]["json"]
    assert body["type"] == "image" and body["image"] == {"id": "media-up", "caption": "*look*"}, body
    assert "filename" not in body["image"], "a photo has no filename field"
    assert sent.id == "wamid.att"

    wa, session = make_client([FakeResponse(200, {"messages": [{"id": "wamid.doc"}]})])
    wa.send_media("user:9", "media-pdf", caption=None, filename="report.pdf", mime="application/pdf")
    body = session.calls[0]["json"]
    assert body["type"] == "document" and body["document"] == {"id": "media-pdf", "filename": "report.pdf"}, body
print("two hops with the token on both; a failure leaves no partial file; caps refuse before spending a request; photos attach as images, PDFs as named documents")

# --------------------------------------------------------------------------- media command and attaching
section("media command and attaching")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token"}
    sdir = Path(home) / "state"
    meta = FakeResponse(200, {"url": "https://lookaside.example/p", "mime_type": "image/png"})

    session = FakeSession([meta, FakeBytes(200, b"PNGDATA")])
    status, out, err = run_cli(["--state-dir", str(sdir), "media", "get", "media-7"], env=env, session=session)
    assert status == 0, (status, err)
    written = Path(out.strip())
    # .resolve() on both sides: the state dir resolves symlinks (/var -> /private/var on macOS)
    assert written.read_bytes() == b"PNGDATA" and written.parent == (sdir / "media").resolve(), written
    assert out.strip().endswith("media-7.png") and len(out.strip().splitlines()) == 1, "one line, the path, nothing else"

    outdir = Path(home) / "elsewhere"
    session = FakeSession([meta, FakeBytes(200, b"PNGDATA")])
    status, out, err = run_cli(["--state-dir", str(sdir), "media", "get", "media-7", "--out", str(outdir)], env=env, session=session)
    assert Path(out.strip()).parent == outdir.resolve(), out

    # sweeping: an old file in our media dir goes, the caller's --out never does
    old_ours = (sdir / "media").resolve() / "old.png"
    old_ours.write_bytes(b"x")
    old_theirs = outdir / "old.png"
    old_theirs.write_bytes(b"x")
    ancient = time.time() - 48 * 3600
    os.utime(old_ours, (ancient, ancient))
    os.utime(old_theirs, (ancient, ancient))
    session = FakeSession([FakeResponse(200, {"id": "media-up"})])
    photo = Path(home) / "chart.png"
    photo.write_bytes(b"\x89PNG" + b"0" * 32)
    status, out, err = run_cli(["--state-dir", str(sdir), "media", "put", str(photo)], env=env, session=session)
    assert status == 0 and out.strip() == "media-up", (status, out, err)
    assert not old_ours.exists(), "a download older than --keep-hours is swept"
    assert old_theirs.exists(), "a file the caller asked for with --out is never swept"

    # send --file uploads then attaches, in one call
    session = FakeSession([FakeResponse(200, {"id": "media-new"}),
                           FakeResponse(200, {"messages": [{"id": "wamid.sent"}]})])
    status, out, err = run_cli(["--state-dir", str(sdir), "send", "the chart", "--to", "user:9", "--file", str(photo)],
                               env=env, session=session)
    assert status == 0 and out.strip() == "wamid.sent", (status, out, err)
    assert session.calls[0]["url"].endswith("/media") and session.calls[1]["json"]["type"] == "image"
    assert session.calls[1]["json"]["image"]["caption"] == "the chart"
    assert store.Store(str(sdir)).seen("wamid.sent"), "an attachment is recorded like any other outgoing message"

    # send --media attaches an existing id, and needs no caption
    session = FakeSession([FakeResponse(200, {"messages": [{"id": "wamid.m"}]})])
    status, out, err = run_cli(["--state-dir", str(sdir), "send", "--to", "user:9", "--media", "media-old"],
                               env=env, session=session)
    assert status == 0 and out.strip() == "wamid.m", (status, out, err)
    assert len(session.calls) == 1, "an existing id is not re-uploaded"

    status, out, err = run_cli(["--state-dir", str(sdir), "send", "--to", "user:9"], env=env, session=FakeSession([]))
    assert status == errors.CODES["bad_usage"].exit_status, "a send with neither text nor attachment is a usage error"
    status, out, err = run_cli(["--state-dir", str(sdir), "send", "x", "--to", "user:9", "--file", str(photo), "--dry-run"],
                               env=env, session=FakeSession([]))
    assert status == errors.CODES["bad_usage"].exit_status, "--dry-run has nothing to rehearse for an attachment"
print("media get writes one path and sweeps only its own directory; media put prints an id; send --file uploads then attaches; send --media reuses; empty send refused")

# --------------------------------------------------------------------------- partial failures
section("partial failures")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token"}
    sdir = str(Path(home) / "state")

    # a three-part send whose second part is refused: part one really arrived, and
    # the caller must be told so, or a retry duplicates it
    long_text = "a" * 4000 + "\n\n" + "b" * 4000 + "\n\n" + "c" * 4000
    session = FakeSession([FakeResponse(200, {"messages": [{"id": "wamid.p1"}]}),
                           FakeResponse(400, {"error": {"code": 131009}})])
    status, out, err = run_cli(["--state-dir", sdir, "send", long_text, "--to", "user:9"], env=env, session=session)
    assert status == errors.CODES["platform_rejected"].exit_status, (status, err)
    assert out.strip() == "wamid.p1", f"the delivered part must be printed before the failure: {out!r}"
    assert store.Store(sdir).seen("wamid.p1"), "and recorded, so a caller can see what went out"
    assert len(session.calls) == 2, "the send stops at the failure rather than pressing on"

    # an upload that succeeds and an attach that fails: the id must not be lost
    photo = Path(home) / "chart.png"
    photo.write_bytes(b"\x89PNG" + b"0" * 32)
    session = FakeSession([FakeResponse(200, {"id": "media-orphan"}),
                           FakeResponse(400, {"error": {"code": 131009}})])
    status, out, err = run_cli(["--state-dir", sdir, "send", "chart", "--to", "user:9", "--file", str(photo)],
                               env=env, session=session)
    assert status == errors.CODES["platform_rejected"].exit_status, (status, err)
    assert "media-orphan" in err and "--media media-orphan" in err, f"the spent upload must be recoverable: {err!r}"

    # attaching an existing id that fails says nothing about uploads, because none happened
    session = FakeSession([FakeResponse(400, {"error": {"code": 131009}})])
    status, out, err = run_cli(["--state-dir", sdir, "send", "x", "--to", "user:9", "--media", "media-given"],
                               env=env, session=session)
    assert "uploaded" not in err, err
print("a delivered part is printed and recorded before a later part fails; a spent upload's id survives a failed attach")

# --------------------------------------------------------------------------- documented codes
section("documented codes")
doc_path = ROOT / "docs" / "errors.md"
doc_rows = {}
for line in doc_path.read_text(encoding="utf-8").splitlines():
    match = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(\d+)\s*\|\s*([^|]+)\|", line)
    if match:
        name, exit_status, retry = match.group(1), int(match.group(2)), match.group(3).strip().lower()
        doc_rows[name] = (exit_status, "yes" in retry)

undocumented = sorted(set(errors.CODES) - set(doc_rows))
assert not undocumented, f"codes with no row in docs/errors.md: {undocumented}"
invented = sorted(set(doc_rows) - set(errors.CODES))
assert not invented, f"docs/errors.md documents codes that do not exist: {invented}"
for name, (exit_status, retry) in doc_rows.items():
    assert errors.CODES[name].exit_status == exit_status, f"{name}: doc says exit {exit_status}, code says {errors.CODES[name].exit_status}"
    assert errors.CODES[name].retry == retry, f"{name}: doc and code disagree on whether retrying helps"
# Retryable means "the other side was unreachable", nothing else. Keeping the set
# explicit means a new code cannot quietly claim a caller should loop on it.
retryable = {name for name, entry in errors.CODES.items() if entry.retry}
assert retryable == {"platform_unavailable", "transcription_unavailable"}, f"unexpected retryable set: {retryable}"

status, out, err = run_cli(["errors"])
assert status == 0, err
printed = {}
for line in out.splitlines():
    parts = line.split()
    if parts and parts[0] in errors.CODES:
        printed[parts[0]] = (int(parts[1]), parts[2] == "yes")
assert printed == doc_rows, f"the errors command and the document disagree: {set(printed.items()) ^ set(doc_rows.items())}"
assert "errors.md" in out, "the command points at the fuller table"

status, out, err = run_cli(["send"])  # no text, no attachment, no state needed
assert err.startswith("error [bad_usage]:"), f"a failure names its code first: {err!r}"
with tempfile.TemporaryDirectory() as home:
    for argv, code in [(["transcribe", "x.ogg"], "bad_usage"),
                       (["send", "hi", "--to", "u"], "no_token"),
                       (["send", "--to", "u", "--file", "/nope/missing.png"], "no_token")]:
        status, out, err = run_cli(argv, env={"HOME": home})
        assert f"error [{code}]:" in err, (argv, err)
assert "errors.md" in (ROOT / "README.md").read_text(encoding="utf-8"), "the README points at the table"
print(f"{len(doc_rows)} codes documented, exit statuses and retry verdicts agreeing across CODES, docs/errors.md and the errors command")

# --------------------------------------------------------------------------- readme
section("readme")
readme = (ROOT / "README.md").read_text(encoding="utf-8")

# the public API the Python example promises
for name in ("WhatsApp", "Store", "WhatsAppError", "Sent", "classify", "CODES"):
    assert name in wa_agent.__all__ and hasattr(wa_agent, name), f"README imports {name}, package does not export it"
for method in ("send_iter", "poll", "download", "upload", "send_media", "typing"):
    assert hasattr(wa_agent.WhatsApp, method), f"README documents WhatsApp.{method}, which does not exist"

# every wa-agent command shown in the README really exists
shown = set(re.findall(r"^wa-agent (?:--\S+ \S+ )*([a-z]+)", readme, re.MULTILINE))
shown |= set(re.findall(r"^\| `([a-z]+)[ <`]", readme, re.MULTILINE))
help_text = run_cli(["--help"])[1]
# A command that does not exist yet may be shown only on a line that says so, so the
# README can announce the relay without ever implying it can be run today.
announced = {m.group(1) for m in re.finditer(r"^wa-agent ([a-z]+)[^\n]*coming soon", readme, re.MULTILINE)}
for command in sorted(shown):
    if command in announced:
        assert command not in help_text, f"`wa-agent {command}` exists now; drop 'coming soon' from the README"
        continue
    assert command in help_text, f"README shows `wa-agent {command}`, which --help does not list"
assert {"send", "recv", "media", "errors"} <= shown, f"the README stopped documenting a command: {shown}"

# claims that would quietly rot
assert f'pip install wa-agent' in readme, "the README must name the distribution, not the repo"
assert "GEMINI_API_KEY" in readme and "OPENROUTER_API_KEY" in readme, "transcription needs a key and the README must say which"
assert "--provider" in readme, "the README must show how the provider is chosen"
assert state.TOKEN_ENV in readme, "the token env var must be named"
assert "docs/errors.md" in readme and "wa-agent errors" in readme
# markdown emphasis sits inside the sentence, so match on the words, not the literal
assert re.search(r"before\W+(\*\*)?the subcommand", readme), "the globals-first gotcha stays documented"
declared_extras = set(project_extras)
mentioned_extras = set(re.findall(r'wa-agent\[([a-z]+)\]', readme))
assert mentioned_extras <= declared_extras, f"the README offers extras that pyproject does not declare: {mentioned_extras - declared_extras}"
for extra in declared_extras - {"dev"}:
    assert f"[{extra}]" in readme, f"pyproject declares the {extra} extra; the README never mentions it"

# every variable the code reads is documented in .env.example
example = (ROOT / ".env.example").read_text(encoding="utf-8")
# literals, not imports: this list is the contract, and it must not quietly shrink
# when a module that defines one of these names is refactored away
for variable in (state.TOKEN_ENV, cli.DEBUG_ENV, "GEMINI_API_KEY", "OPENROUTER_API_KEY", "XDG_STATE_HOME", "XDG_DATA_HOME"):
    assert variable in example, f"{variable} is read by the code but missing from .env.example"
assert "gitignored" in example and "source .env" in example, ".env.example must say how it is loaded"
assert not re.search(r"^[A-Z_]+=\S", example, re.MULTILINE), ".env.example must never carry a value"

# the table of contents lists every section, and every entry points at a real heading
headings = [h for h in re.findall(r"^## (.+)$", readme, re.MULTILINE) if h != "Contents"]
anchors = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}
toc_links = re.findall(r"^- \[[^\]]+\]\(#([^)]+)\)", readme.split("## Contents", 1)[1].split("\n## ", 1)[0], re.MULTILINE)
assert set(toc_links) == anchors, f"README contents and headings disagree: {set(toc_links) ^ anchors}"

# PyPI renders this README as the project page, where a relative link is a 404:
# every link must be absolute or an in-page anchor
relative = re.findall(r"\]\(((?!https?://|#|mailto:)[^)]+)\)", readme)
assert not relative, f"relative links break on the PyPI page: {relative}"

# nothing from a personal setup
for leak in ("_hisab", "_loop", "/Users/", "vault", "VPS", "hamza.6"):
    assert leak.lower() not in readme.lower(), f"README leaks {leak!r}"
print(f".env.example documents every variable the code reads; README's {len(shown - announced)} commands all exist ({len(announced)} marked coming soon), its Python example only uses exported names, and it names the extra, the env var and the error table")

# --------------------------------------------------------------------------- transcription
section("transcription")
with tempfile.TemporaryDirectory() as tmp:
    note = Path(tmp) / "note.ogg"
    note.write_bytes(b"OggS" + b"0" * 64)

    def gemini_ok(text="call me back at six"):
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})

    session = FakeSession([gemini_ok()])
    got = transcribe.transcribe(note, session=session, env={"GEMINI_API_KEY": "gem-key"})
    assert got == "call me back at six", got
    call = session.calls[0]
    assert call["headers"]["x-goog-api-key"] == "gem-key" and "key=" not in call["url"], "the key travels in a header, not a url"
    assert transcribe.DEFAULT_MODEL in call["url"], call["url"]
    part = call["json"]["contents"][0]["parts"][0]["inline_data"]
    assert part["mime_type"] == "audio/ogg" and base64.b64decode(part["data"]) == note.read_bytes(), "the audio goes inline, intact"
    assert "Output only the transcript" in call["json"]["contents"][0]["parts"][1]["text"]

    session = FakeSession([gemini_ok()])
    transcribe.transcribe(note, model="gemini-x", language="urdu", session=session, env={"GEMINI_API_KEY": "k"})
    assert "gemini-x" in session.calls[0]["url"]
    assert "urdu" in session.calls[0]["json"]["contents"][0]["parts"][1]["text"], "a language hint reaches the prompt"

    failures = [
        (FakeResponse(200, {"candidates": []}), "transcription_failed"),          # a refusal answers 200
        (FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "   "}]}}]}), "transcription_failed"),
        (FakeResponse(200, None, "not json"), "transcription_failed"),
        (FakeResponse(400, {"error": {"message": "bad request"}}), "transcription_failed"),
        (FakeResponse(503), "transcription_unavailable"),
        (FakeResponse(429), "transcription_unavailable"),
        (FakeTransportError("dns went away"), "transcription_unavailable"),
    ]
    for response, want in failures:
        try:
            transcribe.transcribe(note, session=FakeSession([response]), env={"GEMINI_API_KEY": "k"})
            raise AssertionError(f"expected {want}")
        except errors.WhatsAppError as exc:
            assert exc.code == want, (want, exc.code)
            assert "k" not in exc.message, "no key material in a message"
    assert errors.CODES["transcription_unavailable"].retry is True, "an unreachable provider is worth retrying"
    assert errors.CODES["transcription_failed"].retry is False, "a refusal is not"

    try:
        transcribe.transcribe(note, session=FakeSession([]), env={})
        raise AssertionError("expected no_transcription_key")
    except errors.WhatsAppError as exc:
        assert exc.code == "no_transcription_key" and exc.exit_status == 12, exc.code
        assert "GEMINI_API_KEY" in exc.detail
    for bad, why in [((Path(tmp) / "nope.ogg"), "a missing file"), ((Path(tmp) / "x.txt"), "a non-audio file")]:
        bad.write_bytes(b"x") if bad.name == "x.txt" else None
        try:
            transcribe.transcribe(bad, session=FakeSession([]), env={"GEMINI_API_KEY": "k"})
            raise AssertionError(f"expected bad_usage for {why}")
        except errors.WhatsAppError as exc:
            assert exc.code == "bad_usage", (why, exc.code)
    try:
        transcribe.transcribe(note, provider="whisper", session=FakeSession([]), env={"GEMINI_API_KEY": "k"})
        raise AssertionError("an unknown provider must be refused")
    except errors.WhatsAppError as exc:
        assert exc.code == "bad_usage" and "unknown transcription provider" in exc.detail, exc.detail

    status, out, err = run_cli(["transcribe", str(note)], env={"GEMINI_API_KEY": "k"}, session=FakeSession([gemini_ok("hello there")]))
    assert status == 0 and out == "hello there\n", (status, repr(out), err)
    assert err == "", "the transcript is all that is printed"
print(f"audio goes inline with the key in a header; {len(failures)} failure modes split into 13 retryable and 14 not; no key exits 12; the command prints only the transcript")

# --------------------------------------------------------------------------- recv --transcribe
section("recv --transcribe")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token", "GEMINI_API_KEY": "gem-key"}
    sdir = str(Path(home) / "state")
    voice = msg("wamid.V", kind="audio", voice=True)
    meta = FakeResponse(200, {"url": "https://lookaside.example/v", "mime_type": "audio/ogg"})

    session = FakeSession([envelope(voice, msg("wamid.T", "typed")), meta, FakeBytes(200, b"OggS-audio"),
                           FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "kal shaam ko aana"}]}}]})])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--transcribe"], env=env, session=session)
    assert status == 0, (status, err)
    delivered = [json.loads(line) for line in out.strip().splitlines()]
    spoken = delivered[0]
    assert spoken["type"] == "audio" and spoken["audio"]["id"] == "media-wamid.V", "the message keeps its shape"
    assert spoken["text"]["body"] == "kal shaam ko aana" and spoken["transcribed"] is True
    assert delivered[1]["id"] == "wamid.T" and "transcribed" not in delivered[1], "a typed message is untouched"
    assert store.Store(sdir).lookup("wamid.V") == "kal shaam ko aana", "the store records words, not <audio …>"
    assert f"transcribed wamid.V" in err, "each billed call prints a line"
    assert not list((Path(sdir).resolve() / "media").glob("*")), "the audio is not kept in the media directory"
    assert not [p for p in Path(sdir).resolve().rglob("*.ogg")], "and not anywhere else in the state directory"

    # a failing provider still delivers the message, marked, and keeps the stream moving
    session = FakeSession([envelope(msg("wamid.W", kind="audio"), next_offset="off-w"), meta,
                           FakeBytes(200, b"OggS"), FakeResponse(503)])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--transcribe"], env=env, session=session)
    assert status == 0, (status, err)
    marked = json.loads(out.strip())
    assert marked["transcribed"] is False and marked["transcription_error"] == "transcription_unavailable", marked
    assert "text" not in marked, "a failed transcription invents no words"
    assert "could not transcribe wamid.W" in err
    assert store.Store(sdir).offset() == "off-w", "the batch still completed"

    # no key: one warning up front, messages still delivered
    session = FakeSession([envelope(msg("wamid.X", kind="audio"), next_offset="off-x"), meta, FakeBytes(200, b"OggS")])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--transcribe"],
                               env={"HOME": home, state.TOKEN_ENV: "secret-token"}, session=session)
    assert status == 0, (status, err)
    assert err.count("GEMINI_API_KEY is not set") == 1, f"warned once, up front: {err!r}"
    assert json.loads(out.strip())["transcribed"] is False
print("a voice note keeps its shape and gains text.body; the audio never lands in the state dir; a failure delivers it marked; no key warns once and carries on")

# --------------------------------------------------------------------------- openrouter transcription
section("openrouter transcription")


def openrouter_ok(text="call me back at six"):
    return FakeResponse(200, {"text": text})


with tempfile.TemporaryDirectory() as tmp:
    note = Path(tmp) / "note.ogg"
    note.write_bytes(b"OggS" + b"0" * 64)
    or_env = {"OPENROUTER_API_KEY": "or-key"}

    # the request shape, pinned
    session = FakeSession([openrouter_ok()])
    got = transcribe.transcribe(note, provider="openrouter", session=session, env=or_env)
    assert got == "call me back at six", got
    call = session.calls[0]
    assert call["verb"] == "POST" and call["url"] == transcribe.OPENROUTER_URL == "https://openrouter.ai/api/v1/audio/transcriptions", call["url"]
    assert call["headers"] == {"Authorization": "Bearer or-key"} and "or-key" not in call["url"], "the key travels in a header"
    assert call["data"] == {"model": transcribe.MODELS["openrouter"]}, call["data"]
    assert call["files"] == {"file": ("note.ogg", note.read_bytes())}, "the audio goes as bytes, named after the file"
    assert "json" not in call, "multipart, not a JSON body"
    session = FakeSession([openrouter_ok()])
    transcribe.transcribe(note, provider="openrouter", model="m-x", language="ur", session=session, env=or_env)
    assert session.calls[0]["data"] == {"model": "m-x", "language": "ur"}, "a model and a language hint reach the form"

    # the same failure mapping as Gemini
    or_failures = [
        (FakeResponse(503), "transcription_unavailable"),
        (FakeResponse(429), "transcription_unavailable"),
        (FakeResponse(408), "transcription_unavailable"),
        (FakeTransportError("dns went away"), "transcription_unavailable"),
        (FakeResponse(400, {"error": {"message": "bad request"}}), "transcription_failed"),
        (FakeResponse(401, {"error": {"message": "no such key"}}), "transcription_failed"),
        (FakeResponse(200, None, "not json"), "transcription_failed"),
        (FakeResponse(200, {}), "transcription_failed"),
        (FakeResponse(200, {"text": ""}), "transcription_failed"),
        (FakeResponse(200, {"text": "   "}), "transcription_failed"),
        (FakeResponse(200, {"text": None}), "transcription_failed"),
    ]
    for response, want in or_failures:
        try:
            transcribe.transcribe(note, provider="openrouter", session=FakeSession([response]), env={"OPENROUTER_API_KEY": "secret-or-key"})
            raise AssertionError(f"expected {want}")
        except errors.WhatsAppError as exc:
            assert exc.code == want, (want, exc.code)
            assert "secret-or-key" not in exc.message + exc.detail, "no key material in a failure"

    # the provider is never guessed from which key is set
    both = {"GEMINI_API_KEY": "gem-key", "OPENROUTER_API_KEY": "or-key"}
    session = FakeSession([FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "from gemini"}]}}]})])
    assert transcribe.transcribe(note, session=session, env=both) == "from gemini"
    assert session.calls[0]["headers"]["x-goog-api-key"] == "gem-key" and "googleapis" in session.calls[0]["url"], "the default is gemini"
    session = FakeSession([openrouter_ok("from openrouter")])
    assert transcribe.transcribe(note, provider="openrouter", session=session, env=both) == "from openrouter"
    assert session.calls[0]["url"] == transcribe.OPENROUTER_URL and session.calls[0]["headers"] == {"Authorization": "Bearer or-key"}
    session = FakeSession([])
    try:
        transcribe.transcribe(note, session=session, env=or_env)
        raise AssertionError("an OpenRouter key alone must not be spent on the default provider")
    except errors.WhatsAppError as exc:
        assert exc.code == "no_transcription_key" and exc.exit_status == 12, exc.code
        assert "GEMINI_API_KEY" in exc.detail, exc.detail
    assert session.calls == [], "nothing was sent"

    # a missing key names the variable actually read
    for provider, key_env, named in [("openrouter", None, "OPENROUTER_API_KEY"), ("gemini", None, "GEMINI_API_KEY"),
                                     ("openrouter", "MY_KEY", "MY_KEY"), ("gemini", "MY_KEY", "MY_KEY")]:
        try:
            transcribe.transcribe(note, provider=provider, key_env=key_env, session=FakeSession([]), env={})
            raise AssertionError("expected no_transcription_key")
        except errors.WhatsAppError as exc:
            assert exc.code == "no_transcription_key" and named in exc.detail, (provider, key_env, exc.detail)
    session = FakeSession([openrouter_ok()])
    transcribe.transcribe(note, provider="openrouter", key_env="MY_KEY", session=session, env={"MY_KEY": "mine", "OPENROUTER_API_KEY": "other"})
    assert session.calls[0]["headers"] == {"Authorization": "Bearer mine"}, "--key-env overrides the provider's own variable"
    neutral = errors.CODES["no_transcription_key"].message.lower()
    assert "gemini" not in neutral and "openrouter" not in neutral, "the fixed message names no provider"
    doc_row = next(l for l in (ROOT / "docs" / "errors.md").read_text(encoding="utf-8").splitlines() if l.startswith("| `no_transcription_key`"))
    assert "GEMINI_API_KEY" in doc_row and "OPENROUTER_API_KEY" in doc_row, "the document names both variables"

    # the commands
    status, out, err = run_cli(["transcribe", str(note), "--provider", "openrouter"], env=or_env, session=FakeSession([openrouter_ok("hello there")]))
    assert status == 0 and out == "hello there\n" and err == "", (status, repr(out), err)
    status, out, err = run_cli(["transcribe", str(note), "--provider", "openrouter"], env={}, session=FakeSession([]))
    assert status == 12 and "error [no_transcription_key]:" in err and "detail: OPENROUTER_API_KEY is not set" in err, (status, err)
    for provider in ("whisper", "openai"):
        status, out, err = run_cli(["transcribe", str(note), "--provider", provider], env={"GEMINI_API_KEY": "k"}, session=FakeSession([]))
        assert status == 2 and "error [bad_usage]:" in err, (provider, status, err)

# recv --transcribe --provider openrouter keeps the message's shape exactly as the Gemini path does
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token", "GEMINI_API_KEY": "gem-key", "OPENROUTER_API_KEY": "or-key"}
    def voice():
        """A fresh message each run: recv folds the words into the dict it is given, so a
        shared one would hand the second run the first run's result, and the comparison
        below would be between a message and itself."""
        return msg("wamid.V", kind="audio", voice=True)

    meta = FakeResponse(200, {"url": "https://lookaside.example/v", "mime_type": "audio/ogg"})
    gem_text = FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "kal shaam ko aana"}]}}]})

    def run_recv(sub_dir, provider_args, responses, run_env=env):
        sdir = str(Path(home) / sub_dir)
        result = run_cli(["--state-dir", sdir, "recv", "--json", "--transcribe", *provider_args], env=run_env, session=FakeSession(responses))
        return sdir, result

    g_dir, (status, out, err) = run_recv("g", [], [envelope(voice()), meta, FakeBytes(200, b"OggS-audio"), gem_text])
    assert status == 0, (status, err)
    via_gemini = json.loads(out.strip())
    o_dir, (status, out, err) = run_recv("o", ["--provider", "openrouter"],
                                         [envelope(voice()), meta, FakeBytes(200, b"OggS-audio"), openrouter_ok("kal shaam ko aana")])
    assert status == 0, (status, err)
    via_openrouter = json.loads(out.strip())
    assert via_openrouter == via_gemini, "the message is identical whichever provider heard it"
    assert via_openrouter["type"] == "audio" and via_openrouter["audio"]["id"] == "media-wamid.V"
    assert via_openrouter["text"]["body"] == "kal shaam ko aana" and via_openrouter["transcribed"] is True
    assert store.Store(o_dir).lookup("wamid.V") == "kal shaam ko aana", "the store records the words"
    assert "transcribed wamid.V" in err
    assert not [p for p in Path(o_dir).resolve().rglob("*.ogg")], "the audio is not kept"

    # a failing OpenRouter delivers the message marked and keeps the stream moving
    _, (status, out, err) = run_recv("f", ["--provider", "openrouter"],
                                     [envelope(msg("wamid.W", kind="audio")), meta, FakeBytes(200, b"OggS"), FakeResponse(503)])
    marked = json.loads(out.strip())
    assert status == 0 and marked["transcribed"] is False and marked["transcription_error"] == "transcription_unavailable", (status, marked)
    assert "text" not in marked

    # no OpenRouter key: one warning naming that variable, message still delivered
    only_gemini = {"HOME": home, state.TOKEN_ENV: "secret-token", "GEMINI_API_KEY": "gem-key"}
    _, (status, out, err) = run_recv("n", ["--provider", "openrouter"],
                                     [envelope(msg("wamid.X", kind="audio")), meta, FakeBytes(200, b"OggS")], run_env=only_gemini)
    assert status == 0, (status, err)
    assert err.count("OPENROUTER_API_KEY is not set") == 1 and "GEMINI_API_KEY" not in err, f"warned once, naming the chosen provider's variable: {err!r}"
    assert json.loads(out.strip())["transcribed"] is False, "a Gemini key was not spent in its place"

    # an unknown provider is refused before anything is requested
    session = FakeSession([])
    status, out, err = run_cli(["--state-dir", str(Path(home) / "u"), "recv", "--transcribe", "--provider", "whisper"], env=env, session=session)
    assert status == 2 and "error [bad_usage]:" in err and session.calls == [], (status, err, session.calls)

# no OpenAI provider, endpoint or key name anywhere the package ships or documents
checked = {**{f"wa_agent/{p.name}": p.read_text(encoding="utf-8") for p in (ROOT / "wa_agent").glob("*.py")},
           **{name: (ROOT / name).read_text(encoding="utf-8") for name in ("README.md", ".env.example", "docs/errors.md")}}
for name, body in checked.items():
    assert not re.search(r"OPENAI_", body), f"{name} names an OpenAI key variable"
    assert "api.openai.com" not in body, f"{name} names an OpenAI endpoint"
assert "openai" not in transcribe.PROVIDERS and "openai" not in transcribe.KEY_ENVS, "OpenAI is not a provider"
# An OpenRouter model id may start with openai/; the one place it lives is the MODELS constant.
mentions = [(name, line.strip()) for name, body in checked.items() for line in body.splitlines() if "openai" in line.lower()]
assert mentions == [("wa_agent/transcribe.py", 'MODELS = {"gemini": DEFAULT_MODEL, "openrouter": "openai/whisper-1", "local": local.DEFAULT_SIZE}')], \
    f"openai appears outside the MODELS constant: {mentions}"
print("openrouter: request shape pinned, failures mapped as for Gemini, the provider never guessed from a key, a missing key names its own variable, recv keeps the message identical, and OpenAI is nowhere but a model id")

# --------------------------------------------------------------------------- local transcription
section("local transcription (library)")


@contextlib.contextmanager
def fake_faster_whisper(spoken=("hello there",), download_fails=False, download_skips=(), transcribe_raises=None, out=None):
    """A stand-in for the `faster_whisper` package, signatures as read from 1.2.1's source.
    The real one is never imported: the check must pass without the extra installed, and
    must never be able to download a model. `log` records what the engine was asked."""
    log = {"constructed": [], "transcribed": [], "downloads": [], "out_at_download": None}

    class WhisperModel:
        def __init__(self, model_size_or_path, device="auto", device_index=0, compute_type="default", **kwargs):
            # the real one downloads anything that is not a directory; record whether it was one
            log["constructed"].append({"path": model_size_or_path, "is_dir": os.path.isdir(model_size_or_path),
                                       "device": device, "compute_type": compute_type})

        def transcribe(self, audio, language=None, vad_filter=False, **kwargs):
            log["transcribed"].append({"audio": audio, "language": language, "vad_filter": vad_filter})
            if transcribe_raises:
                raise transcribe_raises

            def segments():   # a generator, as the real one: nothing happens until it is consumed
                for piece in spoken:
                    yield types.SimpleNamespace(text=piece)
            return segments(), types.SimpleNamespace(language="en")

    def download_model(size_or_id, output_dir=None, local_files_only=False, cache_dir=None, **kwargs):
        log["downloads"].append({"size": size_or_id, "output_dir": output_dir})
        log["out_at_download"] = out.getvalue() if out is not None else None
        if download_fails:
            raise ConnectionError("no route to host")
        target = Path(output_dir)
        target.mkdir(parents=True)
        for name in local.NEEDED_FILES:
            if name not in download_skips:
                (target / name).write_bytes(b"x")
        return str(target)

    module = types.ModuleType("faster_whisper")
    module.__spec__ = importlib.machinery.ModuleSpec("faster_whisper", None)
    module.WhisperModel, module.download_model = WhisperModel, download_model
    saved = sys.modules.get("faster_whisper", "absent")
    sys.modules["faster_whisper"] = module
    local._loaded.clear()
    try:
        yield log
    finally:
        local._loaded.clear()
        if saved == "absent":
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = saved


@contextlib.contextmanager
def no_faster_whisper():
    """The default install: the extra is not there."""
    saved = sys.modules.get("faster_whisper", "absent")
    sys.modules["faster_whisper"] = None   # an import now raises ImportError, whatever is on disk
    local._loaded.clear()
    try:
        yield
    finally:
        local._loaded.clear()
        if saved == "absent":
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = saved


def expect(code, call, *needles):
    try:
        call()
    except errors.WhatsAppError as exc:
        assert exc.code == code, (code, exc.code, exc.detail)
        for needle in needles:
            assert needle in exc.detail, (needle, exc.detail)
        return exc
    raise AssertionError(f"expected {code}")


with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp).resolve()
    note = home / "note.ogg"
    note.write_bytes(b"OggS-audio")
    data = home / "data"
    env = {"HOME": str(home), "XDG_DATA_HOME": str(data)}
    guard = FakeSession([])   # any request at all would land here

    # where models live: XDG data, else ~/.local/share, never the working directory
    cwd = os.getcwd()
    elsewhere = home / "elsewhere"
    elsewhere.mkdir()
    os.chdir(elsewhere)
    try:
        assert state.models_dir(env, create=False) == data / "wa-agent" / "models"
        assert state.models_dir({"HOME": str(home)}, create=False) == home / ".local" / "share" / "wa-agent" / "models"
        assert state.models_dir({"HOME": str(home), "XDG_DATA_HOME": "  "}, create=False) == home / ".local" / "share" / "wa-agent" / "models"
        assert not data.exists() and not (home / ".local").exists(), "looking must not create"
        assert state.models_dir(env) == data / "wa-agent" / "models" and (data / "wa-agent" / "models").is_dir()
        assert elsewhere not in state.models_dir({"HOME": str(home)}, create=False).parents, "not derived from the cwd"
        assert not any(elsewhere.iterdir()), "resolving a models directory wrote into the cwd"
    finally:
        os.chdir(cwd)
    shutil.rmtree(data)

    # the default install: no extra. Asking for local is local_not_ready with the fix, and nothing is created
    with no_faster_whisper():
        assert local.extra_installed() is False
        expect("local_not_ready", lambda: transcribe.transcribe(note, provider="local", session=guard, env=env),
               'pip install "wa-agent[local]"')
        expect("local_not_ready", lambda: local.pull("base", env=env, out=io.StringIO()), 'pip install "wa-agent[local]"')
    assert not data.exists(), "a refused pull or transcription created a directory"
    assert errors.CODES["local_not_ready"].exit_status == 16 and errors.CODES["local_not_ready"].retry is False

    out = io.StringIO()
    with fake_faster_whisper(out=out) as log:
        assert local.extra_installed() is True
        # installed but no model: refused with the command that fixes it, and the engine is never built or asked to download
        expect("local_not_ready", lambda: transcribe.transcribe(note, provider="local", session=guard, env=env),
               "wa-agent model pull base")
        assert log["constructed"] == [] and log["downloads"] == [], "a transcription must never download or build an engine without a model"
        assert not data.exists(), "a refused transcription created a directory"

        # a directory that is missing the tokenizer is not a model: the engine would fetch one from the network
        broken = state.models_dir(env) / "base"
        broken.mkdir()
        for name in ("model.bin", "config.json"):
            (broken / name).write_bytes(b"x")
        assert local.is_ready("base", env) is False and local.installed_sizes(env) == []
        expect("local_not_ready", lambda: transcribe.transcribe(note, provider="local", session=guard, env=env), "model pull")
        assert log["constructed"] == [], "an unready directory must never reach the engine"
        shutil.rmtree(broken)

        # the download: the size is said first, into .partial, then renamed into place
        (state.models_dir(env) / "base.partial").mkdir()   # what a dead earlier attempt leaves
        where = local.pull("base", env=env, out=out)
        assert where == state.models_dir(env) / "base" and local.is_ready("base", env) and local.installed_sizes(env) == ["base"]
        assert log["out_at_download"].startswith('downloading the "base" Whisper model, about 150 MB, to '), log["out_at_download"]
        assert log["downloads"][0]["output_dir"].endswith("base.partial") and log["downloads"][0]["size"] == "base"
        assert not (state.models_dir(env) / "base.partial").exists(), "the partial directory is renamed away"
        assert out.getvalue().rstrip().endswith(f"done: {where}")
        again = io.StringIO()
        local.pull("base", env=env, out=again)
        assert "already downloaded" in again.getvalue() and len(log["downloads"]) == 1, "a present model downloads nothing"

        # transcribing: plain str, no key, no request, built from the directory, the silence filter on
        got = transcribe.transcribe(note, provider="local", session=guard, env=env)
        assert got == "hello there" and type(got) is str, (got, type(got))
        assert guard.calls == [], "the local engine makes no request"
        (built,) = log["constructed"]
        assert built == {"path": str(where), "is_dir": True, "device": "cpu", "compute_type": "int8"}, built
        assert log["transcribed"] == [{"audio": str(note), "language": None, "vad_filter": True}], log["transcribed"]
        transcribe.transcribe(note, provider="local", language="ur", session=guard, env=env)
        assert len(log["constructed"]) == 1, "the model is loaded once per process, not per voice note"
        assert log["transcribed"][-1]["language"] == "ur", "--language is passed through as given"

        # a size that is not on disk is not ready, even when another is
        expect("local_not_ready", lambda: transcribe.transcribe(note, provider="local", model="small", session=guard, env=env),
               "wa-agent model pull small")
        local.pull("tiny", env=env, out=again)
        assert "about 75 MB" in again.getvalue()
        assert transcribe.transcribe(note, provider="local", model="tiny", session=guard, env=env) == "hello there"
        assert len(log["constructed"]) == 2

        # a mistake in the arguments is bad_usage, before the file or the engine is looked at
        expect("bad_usage", lambda: transcribe.transcribe(note, provider="local", model="medium", session=guard, env=env), "tiny, base, small")
        expect("bad_usage", lambda: transcribe.transcribe(note, provider="local", model="base.en", session=guard, env=env), "tiny, base, small")
        expect("bad_usage", lambda: local.pull("large-v3", env=env, out=again), "tiny, base, small")
        expect("bad_usage", lambda: transcribe.transcribe(note, provider="local", key_env="MY_KEY", session=guard, env={**env, "MY_KEY": "k"}),
               "--key-env")

        # local is never chosen by absence: no provider named and no key set is still exit 12, with the extra and a model both present
        expect("no_transcription_key", lambda: transcribe.transcribe(note, session=guard, env=env), "GEMINI_API_KEY")
        assert guard.calls == []

    # segments are joined, blanks dropped; nothing said is a failure, not an empty transcript
    with fake_faster_whisper(spoken=(" first ", "", "  ", "second")) as log:
        assert transcribe.transcribe(note, provider="local", session=guard, env=env) == "first second"
    for silence in ((), ("", "   ")):
        with fake_faster_whisper(spoken=silence):
            expect("transcription_failed", lambda: transcribe.transcribe(note, provider="local", session=guard, env=env), "empty")
    # an engine that falls over is a coded failure, with the reason for the operator and none in the message
    with fake_faster_whisper(transcribe_raises=RuntimeError("decoder blew up")):
        exc = expect("transcription_failed", lambda: transcribe.transcribe(note, provider="local", session=guard, env=env), "decoder blew up")
        assert "decoder" not in exc.message
    # a failed download exits 13 and leaves nothing that looks like a model
    fresh = {"HOME": str(home), "XDG_DATA_HOME": str(home / "data2")}
    with fake_faster_whisper(download_fails=True):
        expect("transcription_unavailable", lambda: local.pull("small", env=fresh, out=io.StringIO()), "no route to host")
        assert not (state.models_dir(fresh, create=False) / "small").exists() and not (state.models_dir(fresh, create=False) / "small.partial").exists()
        assert errors.CODES["transcription_unavailable"].retry is True
    with fake_faster_whisper(download_skips=("tokenizer.json",)):
        expect("transcription_unavailable", lambda: local.pull("small", env=fresh, out=io.StringIO()), "tokenizer.json")
        assert local.is_ready("small", fresh) is False and not (state.models_dir(fresh, create=False) / "small.partial").exists()

print("local (library): the model comes from XDG data and never the cwd; without the extra, or a model, it is local_not_ready naming the fix and builds nothing; "
      "a pull says its size first, goes through .partial, and a failed one leaves nothing ready; a transcription is a plain str, keyless, offline, loaded once, silence-filtered; "
      "sizes are tiny, base and small; --key-env is refused; and no provider named is still exit 12")

section("local transcription (command line)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp).resolve()
    note = home / "note.ogg"
    note.write_bytes(b"OggS-audio")
    env = {"HOME": str(home), "XDG_DATA_HOME": str(home / "data"), state.TOKEN_ENV: "secret-token"}
    guard = FakeSession([])

    # the two commands with the extra absent: both say how to install it, neither makes a directory
    with no_faster_whisper():
        for argv in (["model", "pull"], ["transcribe", str(note), "--provider", "local"]):
            status, out, err = run_cli(argv, env=env, session=guard)
            assert status == 16 and "error [local_not_ready]:" in err and 'pip install "wa-agent[local]"' in err, (argv, status, err)
            assert out == "", "nothing on stdout for a failure"
    assert not (home / "data").exists()

    with fake_faster_whisper() as log:
        # `model pull`: the size first, on stderr, nothing on stdout, and only when asked
        status, out, err = run_cli(["model", "pull"], env=env, session=guard)
        assert status == 0 and out == "", (status, out, err)
        assert err.startswith('downloading the "base" Whisper model, about 150 MB, to '), err
        assert local.is_ready("base", env) and len(log["downloads"]) == 1
        status, out, err = run_cli(["model", "pull", "tiny"], env=env, session=guard)
        assert status == 0 and 'the "tiny" Whisper model, about 75 MB' in err, err
        status, out, err = run_cli(["model", "pull", "tiny"], env=env, session=guard)
        assert status == 0 and "already downloaded" in err and len(log["downloads"]) == 2
        for bad in ("medium", "base.en", "large-v3"):
            status, out, err = run_cli(["model", "pull", bad], env=env, session=guard)
            assert status == 2 and "error [bad_usage]:" in err and "tiny, base, small" in err, (bad, status, err)
        assert len(log["downloads"]) == 2, "a refused size downloads nothing"
        assert "model" in run_cli(["--help"])[1] and "tiny" in run_cli(["model", "pull", "--help"])[1]

        # `transcribe --provider local`: stdout is the transcript, and the caveat is on stderr
        status, out, err = run_cli(["transcribe", str(note), "--provider", "local"], env=env, session=guard)
        assert status == 0 and out == "hello there\n", (status, repr(out), err)
        assert err == "note: transcribed offline by local:base; weak on Urdu and mixed-language speech\n", repr(err)
        status, out, err = run_cli(["transcribe", str(note), "--provider", "local", "--model", "tiny", "--language", "ur"], env=env, session=guard)
        assert status == 0 and "local:tiny" in err and log["transcribed"][-1]["language"] == "ur", (status, err)
        status, out, err = run_cli(["transcribe", str(note), "--provider", "local", "--model", "small"], env=env, session=guard)
        assert status == 16 and "wa-agent model pull small" in err and out == "", (status, err)
        status, out, err = run_cli(["transcribe", str(note), "--provider", "local", "--key-env", "K"], env=env, session=guard)
        assert status == 2 and "--key-env" in err, (status, err)
        status, out, err = run_cli(["transcribe", str(note)], env={**env, "HOME": str(home)}, session=guard)
        assert status == 12 and "GEMINI_API_KEY" in err, "local is never chosen because a key is missing"
        assert guard.calls == [] and len(log["downloads"]) == 2

    # recv --transcribe --provider local
    def voice():
        """A fresh message every time: recv folds the words into the dict it is given, so a
        shared one would carry the last run's tag into the next."""
        return msg("wamid.V", kind="audio", voice=True)

    meta = FakeResponse(200, {"url": "https://lookaside.example/v", "mime_type": "audio/ogg"})
    gem_text = FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "hello there"}]}}]})

    def recv_local(sub, extra, responses, run_env=env):
        sdir = str(home / sub)
        session = FakeSession(responses)
        return sdir, session, run_cli(["--state-dir", sdir, "recv", "--json", "--transcribe", *extra], env=run_env, session=session)

    with fake_faster_whisper() as log:
        local.pull("base", env=env, out=io.StringIO())
        log["downloads"].clear()
        sdir, session, (status, out, err) = recv_local("l", ["--provider", "local"], [envelope(voice()), meta, FakeBytes(200, b"OggS-audio")])
        assert status == 0, (status, err)
        heard = json.loads(out.strip())
        assert heard["transcribed"] is True and heard["transcribed_by"] == "local:base" and heard["text"]["body"] == "hello there", heard
        assert heard["type"] == "audio" and heard["audio"]["id"] == "media-wamid.V", "the message keeps its shape"
        assert store.Store(sdir).lookup("wamid.V") == "hello there", "the store records the words"
        assert "transcribed wamid.V (local:base)" in err
        assert not [p for p in Path(sdir).resolve().rglob("*.ogg")], "the audio is not kept"
        assert not [c for c in session.calls if "googleapis" in c["url"] or "openrouter" in c["url"]], "no provider was called"
        assert log["downloads"] == [], "nothing downloads during recv"
        # apart from the tag, it is the message the Gemini path produces
        _, _, (status, out_g, err_g) = recv_local("g", [], [envelope(voice()), meta, FakeBytes(200, b"OggS-audio"), gem_text],
                                                  run_env={**env, "GEMINI_API_KEY": "gem-key"})
        via_gemini = json.loads(out_g.strip())
        assert {k: v for k, v in heard.items() if k != "transcribed_by"} == via_gemini, (heard, via_gemini, err_g)
        _, _, (status, out_o, err_o) = recv_local("o", ["--provider", "openrouter"], [envelope(voice()), meta, FakeBytes(200, b"OggS-audio"), FakeResponse(200, {"text": "hello there"})],
                                                  run_env={**env, "OPENROUTER_API_KEY": "or-key"})
        assert "transcribed_by" not in out_g and "transcribed_by" not in out_o, "a remote transcript carries no tag: its lines are unchanged"
        assert "(" not in err_g and "(" not in err_o, "and neither does its stderr line"

        # a size that is not on disk: one warning up front naming the fix, the message delivered marked, nothing downloaded
        sdir, session, (status, out, err) = recv_local("m", ["--provider", "local", "--transcribe-model", "small"],
                                                        [envelope(msg("wamid.M", kind="audio"), next_offset="off-m"), meta, FakeBytes(200, b"OggS")])
        assert status == 0, (status, err)
        assert err.count("warning: local transcription is not ready") == 1 and "wa-agent model pull small" in err, err
        marked = json.loads(out.strip())
        assert marked["transcribed"] is False and marked["transcription_error"] == "local_not_ready", marked
        assert "text" not in marked and "transcribed_by" not in marked, "a failed transcription invents no words and claims no engine"
        assert store.Store(sdir).offset() == "off-m", "the batch still completed"
        assert log["downloads"] == [], "recv never downloads, not even to be helpful"

        # arguments that can never work are refused before a single poll
        for extra, needle in ((["--provider", "local", "--key-env", "K"], "--key-env"),
                              (["--provider", "local", "--transcribe-model", "medium"], "tiny, base, small")):
            session = FakeSession([])
            status, out, err = run_cli(["--state-dir", str(home / "r"), "recv", "--transcribe", *extra], env=env, session=session)
            assert status == 2 and "error [bad_usage]:" in err and needle in err and session.calls == [], (extra, status, err)

    # without the extra: one warning naming the install, messages still delivered
    with no_faster_whisper():
        sdir, session, (status, out, err) = recv_local("x", ["--provider", "local"], [envelope(msg("wamid.X", kind="audio")), meta, FakeBytes(200, b"OggS")])
        assert status == 0 and err.count("pip install") == 1, (status, err)
        assert json.loads(out.strip())["transcription_error"] == "local_not_ready"
print("local (command line): model pull says its size on stderr and downloads nothing it was not asked to; transcribe prints the transcript and a caveat on stderr; "
      "recv tags a local transcript with its engine and leaves every remote line untouched; a missing model or extra warns once and delivers the message marked; never a download during recv")

section("local transcription (default install, and the docs)")
# the default install does not pull the engine: it is in an extra and nowhere else
deps_body = raw.split("dependencies = [", 1)[1].split("]", 1)[0]
required = re.findall(r'"([^"]+)"', deps_body)
assert [re.split(r"[<>=!~ ]", name)[0] for name in required] == ["requests"], f"the default install must stay one dependency: {required}"
extras_body = raw.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
extra_lines = {m.group(1): m.group(2) for m in re.finditer(r"^([a-z]+)\s*=\s*\[([^\]]*)\]", extras_body, re.MULTILINE)}
assert "faster-whisper" in extra_lines["local"], "the local extra carries the engine"
assert set(extra_lines) == {"local", "dev"} and "faster-whisper" not in extra_lines["dev"], extra_lines
for heavy in ("faster-whisper", "faster_whisper", "ctranslate2", "onnxruntime", "huggingface"):
    assert heavy not in deps_body, f"{heavy} is in the default dependencies"

# and importing every module of the package, and looking for the extra, never imports it
probe = ("import sys\n"
         "import wa_agent, wa_agent.cli, wa_agent.transcribe, wa_agent.local, wa_agent.doctor\n"
         "from wa_agent import doctor, local\n"
         "env = {'HOME': '/nonexistent'}\n"
         "doctor.check_local(env); local.extra_installed(); local.installed_sizes(env)\n"
         "assert 'faster_whisper' not in sys.modules, 'the engine was imported'\n")
proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT,
                      env={**os.environ, "PYTHONPATH": str(ROOT)})
assert proc.returncode == 0, proc.stderr

# the docs say plainly what the engine is bad at, and how to get it
readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
errors_text = (ROOT / "docs" / "errors.md").read_text(encoding="utf-8")
for name, body in (("README.md", readme_text), ("docs/errors.md", errors_text)):
    assert "Urdu" in body and "Roman Urdu" in body and "switch" in body, f"{name} must say the local engine is weak on Urdu and code-switching"
    assert "confident" in body, f"{name} must say the failure looks like success"
    assert ".en" in body, f"{name} must say why there is no English-only model"
assert 'pip install "wa-agent[local]"' in readme_text and "wa-agent model pull" in readme_text
assert "never chosen for you" in readme_text and "Nothing downloads during `recv`" in readme_text
assert "transcribed_by" in readme_text and "transcribed_by" in errors_text
print("the default install is one dependency and never imports the engine; the extra carries it; README and errors.md say plainly that it is weak on Urdu and code-switching")

# --------------------------------------------------------------------------- recv --download
section("recv --download")
with tempfile.TemporaryDirectory() as home:
    env = {"HOME": home, state.TOKEN_ENV: "secret-token", "GEMINI_API_KEY": "gem-key"}
    sdir = str(Path(home) / "state")
    media_dir = Path(sdir).resolve() / "media"
    photo_meta = FakeResponse(200, {"url": "https://lookaside.example/p", "mime_type": "image/jpeg"})

    # a photo lands in media/ and the message says where
    photo = msg("wamid.P", kind="image", caption="the whiteboard")
    session = FakeSession([envelope(photo, msg("wamid.T2", "typed"), next_offset="off-p"), photo_meta, FakeBytes(200, b"JPEGDATA")])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--download"], env=env, session=session)
    assert status == 0, (status, err)
    got = [json.loads(line) for line in out.strip().splitlines()]
    assert Path(got[0]["path"]).read_bytes() == b"JPEGDATA", got[0]
    assert Path(got[0]["path"]).parent == media_dir, got[0]["path"]
    assert "path" not in got[1], "a text message gains no path"
    assert sum(1 for c in session.calls if "/media/" in c["url"]) == 1, "one metadata hop per photo"

    # the human line shows where the file went
    session = FakeSession([envelope(msg("wamid.P2", kind="image"), next_offset="off-p2"), photo_meta, FakeBytes(200, b"J")])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--download"], env=env, session=session)
    assert "-> " in out and "wamid.P2" in out, out

    # a failed download is delivered marked, and the batch still completes
    session = FakeSession([envelope(msg("wamid.Q", kind="document"), next_offset="off-q"),
                           FakeResponse(200, {"url": "https://lookaside.example/q", "mime_type": "application/pdf"}),
                           FakeBytes(404)])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--download"], env=env, session=session)
    assert status == 0, (status, err)
    marked = json.loads(out.strip())
    assert marked["download_error"] == "media_url_expired" and "path" not in marked, marked
    assert "could not download wamid.Q" in err
    assert store.Store(sdir).offset() == "off-q", "a failed download never stops the batch"

    # --download with --transcribe: the voice note is fetched once, kept, and transcribed from the kept copy
    voice = msg("wamid.VK", kind="audio", voice=True)
    session = FakeSession([envelope(voice, next_offset="off-vk"),
                           FakeResponse(200, {"url": "https://lookaside.example/v", "mime_type": "audio/ogg"}),
                           FakeBytes(200, b"OggS-kept"),
                           FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "kept and heard"}]}}]})])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json", "--download", "--transcribe"], env=env, session=session)
    assert status == 0, (status, err)
    heard = json.loads(out.strip())
    assert heard["text"]["body"] == "kept and heard" and heard["transcribed"] is True, heard
    assert Path(heard["path"]).read_bytes() == b"OggS-kept", "with --download the audio is kept"
    assert sum(1 for c in session.calls if "lookaside" in c["url"]) == 1, "and fetched exactly once"

    # without --download, recv makes no media request at all
    session = FakeSession([envelope(msg("wamid.NOD", kind="image"), next_offset="off-nod")])
    status, out, err = run_cli(["--state-dir", sdir, "recv", "--json"], env=env, session=session)
    assert status == 0 and not any("/media/" in c["url"] for c in session.calls), session.calls
print("a photo lands in media/ with its path in the message; a failed download is delivered marked; --download with --transcribe fetches once and keeps it; no --download, no media request")

# --------------------------------------------------------------------------- doctor
section("doctor")

# Three distinct, made-up secrets, so "never printed" is a search for these exact strings.
DOC_TOKEN = "doctor-token-SECRET-aaaa1111"
DOC_GEMINI = "doctor-gemini-SECRET-bbbb2222"
DOC_OPENROUTER = "doctor-openrouter-SECRET-cccc3333"
DOC_SECRETS = (DOC_TOKEN, DOC_GEMINI, DOC_OPENROUTER)
WA_HOST, GEMINI_HOST, OPENROUTER_HOST = "api.whatsapp.com", "generativelanguage.googleapis.com", "openrouter.ai"


class DoctorSession(FakeSession):
    """Answers by host. `None` means no request to that host is expected: a call there fails
    the check, which is how "an absent key makes no call" is proved."""

    def __init__(self, wa=None, gemini=None, openrouter=None):
        super().__init__([])
        self.answers = {WA_HOST: wa, GEMINI_HOST: gemini, OPENROUTER_HOST: openrouter}

    def request(self, verb, url, headers=None, **kwargs):
        self.calls.append({"verb": verb, "url": url, "headers": headers, **kwargs})
        for host, answer in self.answers.items():
            if host in url:
                assert answer is not None, f"doctor made a request to {host} that this scenario says it must not: {verb} {url}"
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"doctor asked an unknown host: {url}")

    def to(self, host):
        return [c for c in self.calls if host in c["url"]]


def snapshot(root):
    """Every path under root with its bytes and mode: equal before and after means untouched."""
    return sorted((str(p.relative_to(root)), oct(p.stat().st_mode), p.read_bytes() if p.is_file() else None)
                  for p in [root, *root.rglob("*")])


def doctor_lines(out):
    """(status label, check name, message) per check; fix lines come back separately."""
    checks, fixes = [], []
    for line in out.splitlines():
        if line.startswith(" ") and line.strip().startswith("fix:"):
            assert checks, "a fix line with no check above it"
            fixes.append((len(checks) - 1, line.strip()[4:].strip()))
        else:
            label, _, rest = line.partition(" ")
            rest = rest.lstrip()
            for name in ("python", "token", "gemini key", "openrouter key", "local engine", "state dir", "creator"):
                if rest.startswith(name):
                    checks.append((label, name, rest[len(name):].strip()))
                    break
            else:
                raise AssertionError(f"a line that is neither a check nor a fix: {line!r}")
    return checks, dict(fixes)


DOC_ORDER = ["python", "token", "gemini key", "openrouter key", "local engine", "state dir", "creator"]
GOOD_WA, GOOD_KEY = FakeResponse(404, {"error": {"code": 33}}), FakeResponse(200, {"data": {}})

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp).resolve()
    home = tmp / "home"
    home.mkdir()
    sd = tmp / "state"
    sd.mkdir()
    (sd / "creator").write_text("user:demo-1")

    def run_doctor(session, *, state=sd, extra=(), token=DOC_TOKEN, gemini=DOC_GEMINI, openrouter=DOC_OPENROUTER,
                   debug=False, argv_state=True):
        env = {"HOME": str(home)}
        for name, value in (("WHATSAPP_AGENT_TOKEN", token), ("GEMINI_API_KEY", gemini), ("OPENROUTER_API_KEY", openrouter)):
            if value is not None:
                env[name] = value
        if debug:
            env["WHATSAPP_AGENT_DEBUG"] = "1"
        argv = (["--state-dir", str(state)] if argv_state else []) + list(extra) + ["doctor"]
        status, out, err = run_cli(argv, env=env, session=session)
        # the invariants that hold in every scenario, so no scenario can forget them
        assert not any("/updates" in c["url"] for c in session.calls), f"doctor polled: {[c['url'] for c in session.calls]}"
        assert all(c["verb"] == "GET" for c in session.calls), [c["verb"] for c in session.calls]
        assert not any({"json", "data", "files", "params"} & set(c) for c in session.calls), "a probe carried a body"
        for secret in DOC_SECRETS:
            assert secret not in out and secret not in err, f"a secret reached the output (debug={debug}): {out}{err}"
        assert "Traceback" not in out
        return status, out, err

    # 1. all good: seven lines in order, nothing failing, exit 0, exactly one call each
    #    (the local engine line is `optional` here: this environment has no extra)
    session = DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY)
    before = snapshot(tmp)
    status, out, err = run_doctor(session)
    assert status == 0, (out, err)
    checks, fixes = doctor_lines(out)
    assert [c[1] for c in checks] == DOC_ORDER, checks
    assert [c[0] for c in checks] == ["ok", "ok", "ok", "ok", "optional", "ok", "ok"], checks
    assert not fixes and "FAIL" not in out
    assert snapshot(tmp) == before, "doctor wrote something"

    # the token check is one GET on /media/<the named probe id>, through the token's header, and no more
    wa_calls = session.to(WA_HOST)
    assert len(wa_calls) == 1, [c["url"] for c in wa_calls]
    assert wa_calls[0]["url"] == f"{client.BASE}/media/{client.PROBE_MEDIA_ID}", wa_calls[0]["url"]
    assert wa_calls[0]["headers"] == {"Authorization": f"Bearer {DOC_TOKEN}"}
    # each key probe: one bodyless GET on a metadata endpoint, the credential in a header and never in the url
    (g,), (o,) = session.to(GEMINI_HOST), session.to(OPENROUTER_HOST)
    assert g["url"] == "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", g["url"]
    assert g["headers"] == {"x-goog-api-key": DOC_GEMINI}
    assert o["url"] == "https://openrouter.ai/api/v1/key", o["url"]
    assert o["headers"] == {"Authorization": f"Bearer {DOC_OPENROUTER}"}
    for call in (g, o):
        for spend in ("generateContent", "audio/transcriptions", "/chat", "/completions"):
            assert spend not in call["url"], f"a key probe touched a paid endpoint: {call['url']}"
        assert not any(secret in call["url"] for secret in DOC_SECRETS)
    print("all good: seven lines in order (the local engine optional without its extra); one GET a probe on metadata endpoints, credentials in headers, no /updates, nothing written")

    # --key-env is gone: two keys made it ambiguous, and a diagnostic does not need it
    status, out, err = run_cli(["doctor", "--key-env", "X"], env={"HOME": str(home)}, session=DoctorSession())
    assert status == 2, (status, err)
    status, out, err = run_cli(["doctor", "--help"], env={"HOME": str(home)})
    assert "--key-env" not in out and "--provider" not in out

    # 2. a dead token, both spellings: FAIL with the fresh-token fix, exit 15, never "accepted"
    for dead in (FakeResponse(401, {"error": {"code": 190}}), FakeResponse(400, {"error": {"code": 100}})):
        session = DoctorSession(wa=dead, gemini=GOOD_KEY, openrouter=GOOD_KEY)
        status, out, err = run_doctor(session)
        checks, fixes = doctor_lines(out)
        token_line = checks[1]
        assert status == errors.CODES["doctor_failed"].exit_status == 15, (status, err)
        assert token_line[0] == "FAIL" and "rejected" in token_line[2] and "accepted" not in token_line[2], token_line
        assert "fresh token" in fixes[1], fixes
        assert err.startswith("error [doctor_failed]:"), err
        assert "1 of 7 checks failed" in err
    print("a dead token (401, and 400 with error.code 100) fails the token line with a fresh-token fix, exit 15")

    # 3. could not verify: FAIL saying so, and never claiming the token is good
    for unreachable in (FakeTransportError(f"connection reset {DOC_TOKEN} {DOC_GEMINI}"), FakeResponse(429), FakeResponse(503)):
        session = DoctorSession(wa=unreachable, gemini=GOOD_KEY, openrouter=GOOD_KEY)
        status, out, err = run_doctor(session)
        token_line = doctor_lines(out)[0][1]
        assert status == 15 and token_line[0] == "FAIL", (status, out)
        assert "could not reach" in token_line[2] and "accepted" not in token_line[2], token_line
        assert len(session.to(WA_HOST)) == 1, "the probe must not retry"
    # a status the mapping does not know is "unexpected", not "accepted" and not "dead"
    for odd in (FakeResponse(403, {"error": {"code": 10}}), FakeResponse(400, {"error": {"code": 33}})):
        session = DoctorSession(wa=odd, gemini=GOOD_KEY, openrouter=GOOD_KEY)
        status, out, err = run_doctor(session)
        checks, fixes = doctor_lines(out)
        token_line, fix = checks[1], fixes[1]
        assert status == 15 and token_line[0] == "FAIL" and "unexpected" in token_line[2], token_line
        assert "accepted" not in token_line[2] and "fresh token" not in fix, (token_line, fix)
    # 2xx and 404 both read as a good token
    for good in (FakeResponse(200, {}), FakeResponse(404, {})):
        status, out, err = run_doctor(DoctorSession(wa=good, gemini=GOOD_KEY, openrouter=GOOD_KEY))
        assert status == 0 and doctor_lines(out)[0][1][0] == "ok"
    print("unreachable (transport, 429, 503) and unexpected (403, 400/33) fail the token line without calling it good")

    # 4. no usable token: FAIL, and the platform is never asked
    session = DoctorSession(gemini=GOOD_KEY, openrouter=GOOD_KEY)
    status, out, err = run_doctor(session, token=None)
    checks, fixes = doctor_lines(out)
    assert status == 15 and checks[1][0] == "FAIL" and "WHATSAPP_AGENT_TOKEN" in fixes[1], (out, fixes)
    assert not session.to(WA_HOST)
    session = DoctorSession(gemini=GOOD_KEY, openrouter=GOOD_KEY)
    status, out, err = run_doctor(session, token="line-one\nline-two")
    checks, fixes = doctor_lines(out)
    assert status == 15 and checks[1][0] == "FAIL" and "whitespace" in checks[1][2] and "line-one" not in out, out
    assert not session.to(WA_HOST), "a token pasted across two lines must not be sent"
    # a token file: a trailing newline is normal; the file is named, the token is not
    token_file = tmp / "token"
    token_file.write_text(DOC_TOKEN + "\n")
    session = DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY)
    status, out, err = run_doctor(session, token=None, extra=["--token-file", str(token_file)])
    checks = doctor_lines(out)[0]
    assert status == 0 and checks[1][0] == "ok" and "--token-file" in checks[1][2], out
    assert session.to(WA_HOST)[0]["headers"] == {"Authorization": f"Bearer {DOC_TOKEN}"}
    for bad_file in (tmp / "missing", tmp / "empty"):
        (tmp / "empty").write_text("\n")
        session = DoctorSession(gemini=GOOD_KEY, openrouter=GOOD_KEY)
        status, out, err = run_doctor(session, token=None, extra=["--token-file", str(bad_file)])
        assert status == 15 and doctor_lines(out)[0][1][0] == "FAIL" and not session.to(WA_HOST), out
    print("no token, a token with a line break in it, and an unreadable or empty token file fail with no request to the platform; a good file passes")

    # 5. each provider key is its own line and its own outcome
    cases = {
        "gemini": {"var": "GEMINI_API_KEY", "index": 2, "host": GEMINI_HOST, "rejected": (400, 401, 403), "kw": "gemini"},
        "openrouter": {"var": "OPENROUTER_API_KEY", "index": 3, "host": OPENROUTER_HOST, "rejected": (401, 403), "kw": "openrouter"},
    }
    for provider, case in cases.items():
        other = "openrouter" if provider == "gemini" else "gemini"

        def session_for(this):
            return DoctorSession(wa=GOOD_WA, **{provider: this, other: GOOD_KEY})

        def run_with(this, **kw):
            # the other provider's key is set and answers 200, so only this line varies
            return run_doctor(session_for(this), **kw)

        # absent (and a whitespace-only key is absent): optional, and that provider is never called
        for absent in (None, "   "):
            session = DoctorSession(wa=GOOD_WA, **{provider: None, other: GOOD_KEY})
            status, out, err = run_doctor(session, **{provider: absent})
            line = doctor_lines(out)[0][case["index"]]
            assert status == 0, (provider, out)
            assert line[0] == "optional" and case["var"] in line[2], line
            assert not session.to(case["host"]), f"{provider}: an absent key must make no request"
        # accepted
        status, out, err = run_with(FakeResponse(200, {}))
        assert status == 0 and doctor_lines(out)[0][case["index"]][0] == "ok"
        # rejected: FAIL, exit 15, the fix names the variable, and the other provider is unaffected
        for code in case["rejected"]:
            status, out, err = run_with(FakeResponse(code, {"error": {"message": DOC_GEMINI}}))
            checks, fixes = doctor_lines(out)
            line = checks[case["index"]]
            assert status == 15 and line[0] == "FAIL", (provider, code, out)
            assert case["var"] in fixes[case["index"]], fixes
            assert [c[0] for i, c in enumerate(checks) if i != case["index"] and c[1] != "local engine"] == ["ok"] * 5, checks
        # cannot verify: never FAIL, never "ok", exit stays 0 — an optional feature's hiccup must not fail a script
        for unclear in (FakeResponse(503), FakeResponse(429), FakeResponse(500), FakeResponse(404),
                        FakeTransportError(f"timed out talking to a host {DOC_GEMINI} {DOC_OPENROUTER}")):
            status, out, err = run_with(unclear)
            line = doctor_lines(out)[0][case["index"]]
            assert status == 0, (provider, unclear, out)
            assert line[0] == "optional" and "not verified" in line[2], line
    print("each provider key: absent or blank optional with no request; rejected FAIL (gemini 400/401/403, openrouter 401/403); "
          "unreachable, 429, 5xx or an unknown status optional; a rejected key on one provider fails the run whatever the other says")

    # both keys absent is still a passing run
    session = DoctorSession(wa=GOOD_WA)
    status, out, err = run_doctor(session, gemini=None, openrouter=None)
    checks = doctor_lines(out)[0]
    assert status == 0 and [c[0] for c in checks] == ["ok", "ok", "optional", "optional", "optional", "ok", "ok"], out
    assert len(session.calls) == 1, "with no keys, the only request is the token probe"
    print("no keys at all: two optional lines and exit 0")

    # a key pasted across two lines FAILs, naming the variable and never the value, and no request is sent
    # (`requests` would refuse the header before sending, which must not read as an unreachable provider)
    broken = "wskey-part-one-SECRET\nwskey-part-two-SECRET"
    for provider, case in cases.items():
        other = "openrouter" if provider == "gemini" else "gemini"
        # nothing else set: the run makes no request at all
        session = DoctorSession()
        status, out, err = run_doctor(session, **{"token": None, "gemini": None, "openrouter": None, provider: broken})
        assert session.calls == [], f"{provider}: a key with a line break was sent somewhere: {session.calls}"
        checks, fixes = doctor_lines(out)
        line = checks[case["index"]]
        assert status == 15 and line[0] == "FAIL" and "whitespace" in line[2] and case["var"] in line[2], line
        assert "one unbroken line" in fixes[case["index"]] and case["var"] in fixes[case["index"]], fixes
        # with a good token and a good other key, only those are asked
        session = DoctorSession(wa=GOOD_WA, **{provider: None, other: GOOD_KEY})
        status, out, err = run_doctor(session, **{provider: broken})
        assert not session.to(case["host"]), f"{provider}: the broken key reached the provider"
        assert len(session.to(WA_HOST)) == 1 and len(session.to(GEMINI_HOST if other == "gemini" else OPENROUTER_HOST)) == 1
        assert status == 15 and doctor_lines(out)[0][case["index"]][0] == "FAIL"
        for part in ("wskey-part-one", "wskey-part-two"):
            assert part not in out and part not in err, f"{provider}: the value of a key reached the output"
    print("a key with whitespace inside it fails for both providers, naming the variable and never the value, with no request sent")

    # 6. the state directory and the creator; nothing is ever created or written
    fresh = tmp / "not" / "here" / "yet"
    session = DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY)
    before = snapshot(tmp)
    status, out, err = run_doctor(session, state=fresh)
    checks, fixes = doctor_lines(out)
    assert checks[5][0] == "ok" and "does not exist yet" in checks[5][2], checks[5]
    assert checks[6][0] == "FAIL" and "recv" in fixes[6], (checks[6], fixes)     # no creator in a state dir that is not there
    assert status == 15
    assert not fresh.exists() and not fresh.parent.exists(), "doctor created the state directory"
    assert snapshot(tmp) == before, "doctor changed the tree"

    # a state dir that exists and has no creator recorded, then one that does
    empty = tmp / "empty-state"
    empty.mkdir()
    before = snapshot(tmp)
    status, out, err = run_doctor(DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY), state=empty)
    checks, fixes = doctor_lines(out)
    assert checks[5][0] == "ok" and "writable" in checks[5][2] and checks[6][0] == "FAIL", checks
    assert "recv" in fixes[6] and "--to" in fixes[6]
    assert snapshot(tmp) == before, "doctor wrote into the state directory"

    # a file where the directory should be
    blocker = tmp / "a-file"
    blocker.write_text("not a directory")
    status, out, err = run_doctor(DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY), state=blocker)
    checks, fixes = doctor_lines(out)
    assert checks[5][0] == "FAIL" and "not a directory" in checks[5][2] and 5 in fixes, checks
    assert blocker.read_text() == "not a directory"

    # a profile that is not a name: a FAIL line, not a traceback, and the rest still reports
    status, out, err = run_doctor(DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY),
                                  extra=["--profile", "a/b"], argv_state=False)
    checks, fixes = doctor_lines(out)
    assert status == 15 and checks[5][0] == "FAIL" and checks[6][0] == "FAIL" and checks[1][0] == "ok", out
    assert "Traceback" not in err

    # unwritable places are only testable off root (root writes anywhere)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        locked_parent = tmp / "locked"
        locked_parent.mkdir()
        (locked_parent / "existing").mkdir()
        try:
            locked_parent.chmod(0o500)
            (locked_parent / "existing").chmod(0o500)
            for target, want in ((locked_parent / "child", "cannot be created"), (locked_parent / "existing", "not writable")):
                before = snapshot(tmp)
                status, out, err = run_doctor(DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY), state=target)
                checks, fixes = doctor_lines(out)
                assert status == 15 and checks[5][0] == "FAIL" and want in checks[5][2], (target, checks[5])
                assert 5 in fixes
                assert snapshot(tmp) == before
        finally:
            (locked_parent / "existing").chmod(0o700)
            locked_parent.chmod(0o700)
        print("state dir: existing and writable, absent but creatable, a file, a bad profile, an unwritable parent and an unwritable directory; the tree never changes")
    else:
        print("state dir: existing, absent, a file and a bad profile (the unwritable cases are skipped as root); the tree never changes")

    # the creator, recorded, is a passing line
    status, out, err = run_doctor(DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY))
    assert doctor_lines(out)[0][6][0] == "ok"

    # 7. the secrets never appear, in any of the scenarios' shapes, with or without debug
    def shape(n):
        return [
            DoctorSession(wa=GOOD_WA, gemini=GOOD_KEY, openrouter=GOOD_KEY),
            DoctorSession(wa=FakeResponse(401, {"error": {"code": 190, "message": DOC_TOKEN}}), gemini=GOOD_KEY, openrouter=GOOD_KEY),
            DoctorSession(wa=FakeTransportError(f"reset {DOC_TOKEN}"), gemini=FakeTransportError(f"reset {DOC_GEMINI}"),
                          openrouter=FakeTransportError(f"reset {DOC_OPENROUTER}")),
            DoctorSession(wa=FakeResponse(403, {"error": {"message": DOC_TOKEN}}), gemini=FakeResponse(403, {"error": DOC_GEMINI}),
                          openrouter=FakeResponse(401, {"error": DOC_OPENROUTER})),
        ][n]

    for n in range(4):
        for debug in (False, True):
            status, out, err = run_doctor(shape(n), debug=debug)   # run_doctor asserts no secret in out or err
            if debug and status != 0:
                assert "Traceback" in err, "debug should add a traceback, which is still free of secrets"
    print("the token and both provider keys never appear in stdout or stderr: pass, dead, unreachable and unexpected, with and without WHATSAPP_AGENT_DEBUG=1")

    # 8. the python line, and the floor agrees with the packaging
    requires = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
    assert requires, "requires-python is no longer a simple >=X.Y"
    assert doctor.MIN_PYTHON == (int(requires.group(1)), int(requires.group(2))), "doctor's floor and requires-python disagree"
    assert doctor.check_python((3, 9, 6)).status == "fail" and "install Python" in doctor.check_python((3, 9, 6)).fix
    assert doctor.check_python((3, 10, 0)).status == "ok" and doctor.check_python((4, 0, 0)).status == "ok"
    old_python = doctor.run_checks(state_dir_override=str(sd), env={"HOME": str(home), "WHATSAPP_AGENT_TOKEN": DOC_TOKEN},
                                   session=DoctorSession(wa=GOOD_WA), python_version=(3, 9, 0))
    assert old_python[0].status == "fail" and doctor.failed(old_python) == [old_python[0]]
    print(f"python floor {doctor.MIN_PYTHON} agrees with requires-python; an older interpreter fails the first line")

    # every transcription provider has a key probe, and the variable each is read from is transcribe's own
    assert set(doctor.KEY_PROBES) == set(transcribe.KEYED_PROVIDERS) == set(transcribe.KEY_ENVS)
    for provider in transcribe.KEYED_PROVIDERS:
        assert transcribe.KEY_ENVS[provider] in doctor.check_key(provider, env={}).message
    print("every transcription provider has a key probe, read from the variable transcribe names")

    # `local` is the one provider with no key, so it has no probe and no key line; it has its own line instead
    assert set(transcribe.PROVIDERS) - set(doctor.KEY_PROBES) == {"local"} and "local" not in transcribe.KEY_ENVS
    assert transcribe.key_env_for("local") is None and transcribe.KEYED_PROVIDERS == ("gemini", "openrouter")

    # the local engine line: optional until it could run, ok when it could, never FAIL, and it does nothing but look
    denv = {"HOME": str(home)}
    models = home / ".local" / "share" / "wa-agent" / "models"
    before = snapshot(tmp)
    with no_faster_whisper():
        line = doctor.check_local(denv)
        assert line.status == "optional" and line.name == "local engine" and 'pip install "wa-agent[local]"' in line.message and line.fix == "", line
    with fake_faster_whisper() as log:
        line = doctor.check_local(denv)
        assert line.status == "optional" and "no model is downloaded" in line.message and "wa-agent model pull" in line.message, line
        assert not models.exists(), "looking for models created a directory"
        (models / "base.partial").mkdir(parents=True)
        for name in local.NEEDED_FILES:
            (models / "base.partial" / name).write_bytes(b"x")
        assert doctor.check_local(denv).status == "optional", "a half-finished download is not a model"
        (models / "small").mkdir()
        (models / "small" / "model.bin").write_bytes(b"x")
        assert doctor.check_local(denv).status == "optional", "a directory without every file is not a model"
        assert log["constructed"] == [] and log["downloads"] == [] and log["transcribed"] == [], "doctor built an engine or downloaded"
    shutil.rmtree(home / ".local")
    assert snapshot(tmp) == before, "the local engine line wrote something"
    with fake_faster_whisper() as log:
        local.pull("base", env=denv, out=io.StringIO())
        local.pull("tiny", env=denv, out=io.StringIO())
        log["downloads"].clear()
        after_pull = snapshot(tmp)
        line = doctor.check_local(denv)
        assert line.status == "ok" and "tiny, base" in line.message and str(models) in line.message and line.fix == "", line
        session = DoctorSession(wa=GOOD_WA, gemini=None, openrouter=None)
        status, out, err = run_doctor(session, gemini=None, openrouter=None)
        checks, fixes = doctor_lines(out)
        assert status == 0 and checks[4][:2] == ("ok", "local engine") and not fixes, out
        assert session.to(GEMINI_HOST) == [] and session.to(OPENROUTER_HOST) == [], "the local line made a request"
        assert log["constructed"] == [] and log["downloads"] == [], "doctor built an engine or downloaded"
        assert snapshot(tmp) == after_pull, "doctor wrote something"
    shutil.rmtree(home / ".local")
    print("the local engine line: optional without the extra or without a whole model (a .partial is not one), ok naming the sizes on disk; "
          "it builds no engine, downloads nothing, makes no request and creates nothing")

# --------------------------------------------------------------------------- client.probe_token
section("client.probe_token")
for status, payload, verdict in [
    (404, {"error": {"code": 33}}, True), (200, {}, True),
]:
    wa, session = make_client([FakeResponse(status, payload)])
    assert wa.probe_token() is verdict, status
    (call,) = session.calls
    assert call["verb"] == "GET" and call["url"] == f"{client.BASE}/media/{client.PROBE_MEDIA_ID}", call["url"]
    assert call["headers"] == {"Authorization": "Bearer secret-token"}
    assert "/updates" not in call["url"] and not ({"json", "data", "files"} & set(call))
for status, payload, code in [
    (401, {"error": {"code": 190}}, "auth"), (400, {"error": {"code": 100}}, "auth"),
    (400, {"error": {"code": 33}}, "platform_rejected"), (403, {}, "platform_rejected"), (410, None, "platform_rejected"),
    (429, {}, "platform_unavailable"), (503, {}, "platform_unavailable"), (500, {}, "platform_unavailable"),
    (408, {}, "platform_unavailable"),
]:
    wa, session = make_client([FakeResponse(status, payload)])
    try:
        wa.probe_token()
        raise AssertionError(f"probe_token accepted a {status}")
    except errors.WhatsAppError as exc:
        assert exc.code == code, (status, exc.code)
        assert isinstance(exc, errors.AuthError) == (code == "auth")
    assert len(session.calls) == 1, "the probe is one request: no retry past a 429, no second hop"
wa, session = make_client([FakeTransportError("boom")])
try:
    wa.probe_token()
    raise AssertionError("a transport error must raise")
except errors.WhatsAppError as exc:
    assert exc.code == "platform_unavailable"
assert isinstance(client.PROBE_MEDIA_ID, str) and client.PROBE_MEDIA_ID and 404 in client.PROBE_ACCEPTED
assert "UNCONFIRMED" in (ROOT / "wa_agent" / "client.py").read_text(encoding="utf-8"), "the probe mapping must say it is unconfirmed"

# it is paced like any other media_get: the 13th probe in a minute waits for the window
wa, session = make_client([GOOD_WA] * 13)
start = wa.limits._now()
for _ in range(13):
    wa.probe_token()
assert wa.limits._now() - start >= 40, "probe_token must go through the media_get limiter"
assert not any("/updates" in c["url"] for c in session.calls)
print("probe_token: 404 and 2xx accept; 401 and 400/100 are AuthError; 429/5xx/transport are platform_unavailable; anything else platform_rejected; "
      "one GET, bearer header, never /updates, paced by media_get")

# --------------------------------------------------------------------------- module entry point
section("module entry point")
proc = subprocess.run([sys.executable, "-m", "wa_agent", "--version"], capture_output=True, text=True, cwd=ROOT,
                      env={**os.environ, "PYTHONPATH": str(ROOT)})
assert proc.returncode == 0, proc.stderr
assert installed in proc.stdout, proc.stdout
# a command that needs no state and no network: this proves the entry point, not a feature
proc = subprocess.run([sys.executable, "-m", "wa_agent", "errors"], capture_output=True, text=True, cwd=ROOT,
                      env={**os.environ, "PYTHONPATH": str(ROOT)})
assert proc.returncode == 0, proc.stderr
assert "platform_rejected" in proc.stdout, proc.stdout[:200]
assert "Traceback" not in proc.stderr, proc.stderr
print("python -m wa_agent matches the installed command, including its exit status")

# --------------------------------------------------------------------------- no stray state
section("no stray state")
# Anything hidden is a tool's own business (.git, .venv, .live-state), as are build
# outputs; what matters is that a check run leaves no cursor, log or media in the
# tracked tree.
IGNORED_DIRS = {"build", "dist"}
strays = [
    str(p.relative_to(ROOT))
    for p in ROOT.rglob("*")
    if not any(part.startswith(".") or part in IGNORED_DIRS or part.endswith(".egg-info") for part in p.relative_to(ROOT).parts)
    and (p.name in ("offset", "messages.jsonl", "creator") or p.suffix == ".jsonl")
]
assert not strays, f"the check left state behind: {strays}"
print("no cursor, store or media artifact anywhere in the repo")

print("\nall checks passed")
