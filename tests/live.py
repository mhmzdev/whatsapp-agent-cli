#!/usr/bin/env python3
"""A real round trip against a real agent — the half `tests/smoke.py` cannot reach.

    make live                 # everything your .env allows
    make live ARGS="--send-only"
    make live ARGS="--audio note.ogg"

Reads `.env` from the repository root if it is there (this script does; the CLI
deliberately does not). Whatever is missing is skipped with a warning rather than
failing the run, so a partial setup still proves what it can.

Nothing here touches your real state directory: everything lands in `.live-state/`,
which `make clean` removes.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".live-state"
CLI = ROOT / ".venv" / "bin" / "whatsapp-agent"

GREEN, YELLOW, RED, DIM, OFF = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def load_dotenv(path=ROOT / ".env"):
    """Only this script reads .env. The CLI takes its token from the environment."""
    if not path.exists():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            found[key.strip()] = value
    os.environ.update({k: v for k, v in found.items() if not os.environ.get(k)})
    return found


def run(*args, env=None, check=False):
    """Run the CLI, echo what was run, return (status, stdout, stderr)."""
    cmd = [str(CLI), "--state-dir", str(STATE), *args]
    print(f"{DIM}$ whatsapp-agent {' '.join(args)}{OFF}")
    proc = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    for line in proc.stdout.splitlines():
        print(f"  {line}")
    for line in proc.stderr.splitlines():
        print(f"  {DIM}{line}{OFF}")
    if check and proc.returncode != 0:
        print(f"{RED}  ↑ exited {proc.returncode}{OFF}")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def step(title):
    print(f"\n{GREEN}▸ {title}{OFF}")


def skip(why):
    print(f"{YELLOW}  skipped: {why}{OFF}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--send-only", action="store_true", help="do not poll (leave another poller's cursor alone)")
    ap.add_argument("--audio", metavar="PATH", help="a voice note to transcribe; synthesized on macOS when omitted")
    ap.add_argument("--to", metavar="USER", help="recipient, when no creator has been recorded yet")
    ap.add_argument("--wait", type=int, default=25, metavar="S", help="seconds to wait for a reply (default: %(default)s)")
    args = ap.parse_args()

    if not CLI.exists():
        sys.exit("run `make dev` first")
    loaded = load_dotenv()
    STATE.mkdir(parents=True, exist_ok=True)
    print(f"{DIM}state: {STATE}{OFF}")
    if loaded:
        print(f"{DIM}.env supplied: {', '.join(sorted(loaded))}{OFF}")

    token = os.environ.get("WHATSAPP_AGENT_TOKEN", "").strip()
    gemini = os.environ.get("GEMINI_API_KEY", "").strip()

    # ---------------------------------------------------------------- no credentials needed
    step("the tool itself")
    run("--version", check=True)
    status, out, _ = run("errors")
    print(f"  {DIM}{len(out.splitlines()) - 4} codes documented{OFF}")

    step("what a long message would look like (no token needed)")
    # long enough to actually split, so the (i/n) numbering is visible rather than described
    body = "**Deploy finished**\n\n- 3 tests failed\n- logs attached\n\n" + "\n\n".join(
        f"paragraph {i}: " + ("detail. " * 90) for i in range(1, 7))
    status, out, _ = run("send", body, "--to", "user:0", "--dry-run")
    print(f"  {DIM}would send as {out.count('---')} parts{OFF}")

    # ---------------------------------------------------------------- transcription
    step("transcription")
    audio = args.audio
    if not audio and shutil.which("say") and shutil.which("afconvert"):
        tmp = STATE / "sample.m4a"
        subprocess.run(["say", "-o", str(STATE / "sample.aiff"),
                        "Please remind me about the meeting at four and send the invoice"], check=False)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(STATE / "sample.aiff"), str(tmp)], check=False)
        audio = str(tmp) if tmp.exists() else None
        if audio:
            print(f"  {DIM}synthesized a sample voice note{OFF}")
    if not gemini:
        skip("GEMINI_API_KEY is not set — voice notes would arrive marked transcribed: false")
    elif not audio:
        skip("no audio file; pass --audio PATH")
    else:
        started = time.time()
        status, out, _ = run("transcribe", audio)
        if status == 0:
            print(f"  {DIM}{time.time() - started:.1f}s{OFF}")

    # ---------------------------------------------------------------- whatsapp
    if not token:
        step("WhatsApp")
        skip("WHATSAPP_AGENT_TOKEN is not set — nothing was sent or received")
        print(f"\n{DIM}copy .env.example to .env and fill it in, then run this again{OFF}")
        return 0

    step("who you are")
    recipient = args.to
    if not recipient and not args.send_only:
        print(f"  {DIM}polling once to learn the creator; send anything to the agent now{OFF}")
        status, out, err = run("recv", "--json", "--timeout", str(min(args.wait, 25)))
        if status == 9:
            print(f"{RED}  another poller holds this token. Stop it, or use --send-only.{OFF}")
            return 9
        if status != 0:
            print(f"{RED}  could not poll (exit {status}){OFF}")
            return status
        for line in out.splitlines():
            recipient = json.loads(line).get("from") or recipient
    if not recipient:
        skip("no creator recorded yet — text the agent once, or pass --to user:<id>")
        return 0
    print(f"  {DIM}recipient resolved{OFF}")

    step("send")
    stamp = time.strftime("%H:%M:%S")
    run("send", f"live test at {stamp} — reply to this and I will read it back", "--to", recipient, check=True)

    if args.send_only:
        print(f"\n{GREEN}done (send-only). Check your phone.{OFF}")
        return 0

    step(f"read the reply (waiting up to {args.wait}s — reply on your phone now)")
    deadline = time.time() + args.wait
    seen = False
    while time.time() < deadline and not seen:
        flags = ["recv", "--json", "--timeout", "20"]
        if gemini:
            flags.append("--transcribe")
        status, out, err = run(*flags)
        if status == 9:
            print(f"{RED}  another poller took the cursor mid-run{OFF}")
            return 9
        for line in out.splitlines():
            message = json.loads(line)
            words = (message.get("text") or {}).get("body", "")
            kind = message.get("type")
            mark = " (transcribed)" if message.get("transcribed") else ""
            print(f"  {GREEN}←{OFF} {kind}{mark}: {words[:120]}")
            seen = True
    if not seen:
        skip("nothing arrived in time — not a failure, just nobody replied")

    print(f"\n{GREEN}done. State in {STATE}; `make clean` removes it.{OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
