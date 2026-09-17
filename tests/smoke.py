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
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import whatsapp_agent  # noqa: E402
from whatsapp_agent import cli, client, errors, media, ratelimit, state, store, text  # noqa: E402

FORBIDDEN = ("Traceback", 'HTTP', '{"error"', "OAuthException", "gemini", "openai")


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
try:
    import tomllib  # 3.11+
except ModuleNotFoundError:
    parsed_by = "regex (no tomllib before 3.11)"
else:
    real = tomllib.loads(raw)["project"]
    assert {k: real[k] for k in pyproject} == pyproject, f"{pyproject} disagrees with tomllib {real}"
    parsed_by = "regex, agreeing with tomllib"
assert pyproject["name"] == "whatsapp-agent", pyproject["name"]
declared = pyproject["version"]
assert declared.count(".") == 2 and all(p.isdigit() for p in declared.split(".")), declared
installed = whatsapp_agent.__version__
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
stubs = [(["transcribe", "note.ogg"], 7)]
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

    status, out, err = run_cli(base + ["--transcribe"], env=env, session=FakeSession([]))
    assert status == errors.CODES["not_implemented"].exit_status and "#7" in err, (status, err)

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

# --------------------------------------------------------------------------- module entry point
section("module entry point")
proc = subprocess.run([sys.executable, "-m", "whatsapp_agent", "--version"], capture_output=True, text=True, cwd=ROOT,
                      env={**os.environ, "PYTHONPATH": str(ROOT)})
assert proc.returncode == 0, proc.stderr
assert installed in proc.stdout, proc.stdout
# a command that is still a stub: this proves the entry point, not the feature,
# and a real one would resolve real state on the developer's machine.
proc = subprocess.run([sys.executable, "-m", "whatsapp_agent", "transcribe", "note.ogg"], capture_output=True, text=True, cwd=ROOT,
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
