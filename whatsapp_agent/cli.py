"""The command-line front door. Every subcommand is a thin wrapper over the
library; the library is what hisab-whatsapp and anything else import.

argparse rather than click or typer: a transport library that pushes a CLI
framework into every dependent's environment is a worse library, and this
surface is small enough that the standard library covers it.

The subcommands below parse their arguments and then fail with
`not_implemented` until their own ticket lands — #7 transcribe. They exit non-zero on purpose: a stub that exits 0 would make an
unimplemented command look like a passing one.
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import __version__
from . import media as media_types
from .client import WhatsApp
from .errors import CODES, WhatsAppError, classify, exit_status
from .state import DEFAULT_PROFILE, TOKEN_ENV, resolve_token, state_dir
from .store import Store
from .text import DEFAULT_CHUNK, chunks, numbered, to_whatsapp

DEBUG_ENV = "WHATSAPP_AGENT_DEBUG"


def _todo(command, issue):
    raise WhatsAppError("not_implemented", f"{command} lands in #{issue}")


def _send(args, env=None, session=None):
    """Send a text, or attach a file. Recipient: --to, else the creator recv recorded."""
    # "you gave me nothing to send" comes before "I do not know who to send it to":
    # it is the more fundamental mistake, and it needs no state to notice.
    if not (args.text or args.file or args.media):
        raise WhatsAppError("bad_usage", "nothing to send: give some text, --file or --media")

    directory = state_dir(args.profile, args.state_dir, env=env)
    store = Store(directory)
    to = args.to or store.creator()
    if not to:
        raise WhatsAppError("no_recipient", "no --to and no creator recorded yet")

    if args.file or args.media:
        if args.dry_run:
            raise WhatsAppError("bad_usage", "--dry-run has nothing to rehearse for an attachment")
        client = WhatsApp(resolve_token(args.token_file, env=env), session=session)
        if args.file:
            path = Path(args.file).expanduser()
            mime = args.type or media_types.guess_type(path)
            media_id = client.upload(path, mime)
            filename = path.name
        else:
            media_id, mime, filename = args.media, args.type, None
        try:
            sent = client.send_media(to, media_id, caption=args.text, filename=filename, mime=mime)
        except WhatsAppError:
            # The upload succeeded and has already cost one of twelve media requests
            # a minute. Say what the id is, so a retry attaches it instead of
            # uploading the same bytes again.
            if args.file:
                print(f"note: the file was uploaded as {media_id}; retry with --media {media_id}",
                      file=sys.stderr, flush=True)
            raise
        store.add(sent.id, "out", sent.text)
        print(sent.id)
        return

    if args.dry_run:
        # Rehearse a long message without spending one: the same conversion and
        # split the wire would see, no call, no store record, no token needed.
        for part in numbered(chunks(to_whatsapp(args.text), DEFAULT_CHUNK)):
            print(part)
            print("---")
        return

    client = WhatsApp(resolve_token(args.token_file, env=env), session=session)
    # send_iter, not send: a part that made it is printed and recorded before a
    # later part can fail, so a failure never hides what was already delivered.
    for sent in client.send_iter(to, args.text):
        store.add(sent.id, "out", sent.text)
        print(sent.id, flush=True)


BACKOFF_START = 1
BACKOFF_CAP = 60


def _human(message):
    """One line per message: when, who, what kind, and the text or a placeholder."""
    kind = message.get("type", "?")
    when = time.strftime("%H:%M:%S", time.localtime(int(message.get("timestamp", time.time()))))
    who = message.get("from", "?")
    if kind == "text":
        what = (message.get("text") or {}).get("body", "")
    else:
        payload = message.get(kind) or {}
        media_id = payload.get("id", "")
        caption = payload.get("caption", "")
        what = f"<{kind}{' ' + media_id if media_id else ''}>{' ' + caption if caption else ''}"
    return f"{when}  {who}  {what}"


def _text_of(message):
    """What to record in the store: the body for text, a short placeholder otherwise.
    The bytes behind a media id are #6's business, and transcription is #7's."""
    if message.get("type") == "text":
        return (message.get("text") or {}).get("body", "")
    return _human(message).split("  ", 2)[-1]


def _deliver(message, store, client, as_json, typing):
    """Print, then record, then let the caller advance the cursor.

    That order is deliberate: killed between printing and recording, the message
    arrives again next run; the other order would mark it seen and let nobody ever
    see it. A visible duplicate beats a silent loss.
    """
    line = json.dumps(message, ensure_ascii=False) if as_json else _human(message)
    print(line, flush=True)
    store.add(message.get("id"), "in", _text_of(message))
    sender = message.get("from")
    if sender:
        store.set_creator(sender)
    if typing and client is not None:
        client.typing(message.get("id"))


def _sweep(directory, keep_hours, now=time.time):
    """Drop downloads older than keep_hours from our own media directory.

    Only ever this directory: a file the caller asked for with --out is theirs.
    Returns how many were removed.
    """
    media_dir = Path(directory) / "media"
    if not media_dir.is_dir() or keep_hours <= 0:
        return 0
    cutoff = now() - keep_hours * 3600
    removed = 0
    for path in media_dir.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _media(args, env=None, session=None):
    directory = state_dir(args.profile, args.state_dir, env=env)
    client = WhatsApp(resolve_token(args.token_file, env=env), session=session)
    _sweep(directory, args.keep_hours)

    if args.media_command == "get":
        # Resolved, so the one line this prints is an absolute, canonical path a
        # shell can hand straight to another command.
        dest = Path(args.out).expanduser().resolve() if args.out else Path(directory) / "media"
        path, _mime = client.download(args.media_id, dest)
        print(path)
        return
    print(client.upload(Path(args.path).expanduser(), args.type))


def _recv(args, env=None, session=None, sleep=time.sleep):
    directory = state_dir(args.profile, args.state_dir, env=env)
    store = Store(directory)
    if args.transcribe:
        raise WhatsAppError("not_implemented", "recv --transcribe lands in #7")
    client = WhatsApp(resolve_token(args.token_file, env=env), session=session)

    backoff = BACKOFF_START
    replay = args.replay
    while True:
        try:
            messages, next_offset = client.poll(store.offset(), limit=args.limit,
                                                timeout=args.timeout, replay=replay)
        except WhatsAppError as exc:
            # auth and another_poller are permanent; only unavailability is worth waiting out,
            # and only when the caller asked us to keep going.
            if exc.code != "platform_unavailable" or not args.follow:
                raise
            # The code's message ends with advice ("retrying may help") that would read
            # oddly next to the actual retry; the first clause is the fact.
            print(f"warning: {exc.message.split(';')[0]} — retrying in {backoff}s",
                  file=sys.stderr, flush=True)
            sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)
            continue

        backoff = BACKOFF_START
        replay = False  # only the first poll of a run may ask for the backlog
        try:
            for message in messages:
                if store.seen(message.get("id")):
                    continue
                _deliver(message, store, client, args.json, args.typing)
        except BrokenPipeError:
            # `recv | head` closed the pipe. Stopping without advancing means the
            # undelivered tail of this batch comes back on the next run.
            return
        store.set_offset(next_offset)

        if not args.follow:
            return


def build_parser():
    parser = argparse.ArgumentParser(
        prog="whatsapp-agent",
        description="Talk to the WhatsApp Agent Platform: send, receive, media, transcription.",
        epilog=f"Token: ${TOKEN_ENV}, or --token-file. State: $XDG_STATE_HOME/whatsapp-agent/<profile>.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--token-file", metavar="PATH", help=f"file holding the token; ${TOKEN_ENV} wins over it")
    parser.add_argument("--state-dir", metavar="PATH", help="override where the cursor, store and media live")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, metavar="NAME", help="state under this profile name (default: %(default)s)")

    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p_send = sub.add_parser("send", help="send a message to the creator")
    p_send.add_argument("text", nargs="?", help="the message body, or the caption when attaching")
    p_send.add_argument("--to", metavar="USER", help="recipient id (default: the creator recv recorded)")
    p_send.add_argument("--dry-run", action="store_true", help="print the parts that would be sent, send nothing")
    p_send.add_argument("--file", metavar="PATH", help="upload this file and attach it; the text becomes its caption")
    p_send.add_argument("--media", metavar="ID", help="attach an already-uploaded media id")
    p_send.add_argument("--type", metavar="MIME", help="content type of --file or --media (default: guessed from the name)")
    p_send.set_defaults(func=_send)

    p_recv = sub.add_parser("recv", help="read new messages since the stored cursor")
    p_recv.add_argument("--follow", action="store_true", help="hold the long-poll open and stream")
    p_recv.add_argument("--json", action="store_true", help="one JSON object per line")
    p_recv.add_argument("--transcribe", action="store_true", help="replace a voice note with its transcript")
    p_recv.add_argument("--typing", action="store_true", help="mark each delivered message read and show the typing indicator")
    p_recv.add_argument("--limit", type=int, default=50, metavar="N", help="messages per poll (default: %(default)s)")
    p_recv.add_argument("--timeout", type=int, default=20, metavar="S", help="seconds to hold one poll open, max 25 (default: %(default)s)")
    p_recv.add_argument("--replay", action="store_true", help="on a first run, ask for the backlog the platform still holds (up to 30 days)")
    p_recv.set_defaults(func=_recv)

    p_media = sub.add_parser("media", help="download or upload media")
    p_media.add_argument("--keep-hours", type=int, default=24, metavar="H",
                         help="sweep downloads in the state dir older than this (default: %(default)s; 0 disables)")
    media_sub = p_media.add_subparsers(dest="media_command", metavar="<get|put>", required=True)
    p_get = media_sub.add_parser("get", help="download media by id")
    p_get.add_argument("media_id")
    p_get.add_argument("--out", metavar="DIR", help="directory to write into (default: the state dir)")
    p_get.set_defaults(func=_media)
    p_put = media_sub.add_parser("put", help="upload a file and print its media id")
    p_put.add_argument("path")
    p_put.add_argument("--type", metavar="MIME", help="content type (default: guessed from the extension)")
    p_put.set_defaults(func=_media)

    p_err = sub.add_parser("errors", help="list every exit code and what it means")
    p_err.set_defaults(func=_errors)

    p_tr = sub.add_parser("transcribe", help="turn an audio file into text")
    p_tr.add_argument("path")
    p_tr.set_defaults(func=lambda args: _todo("transcribe", 7))

    return parser


def main(argv=None, env=None, session=None, sleep=None):
    """`session` and `sleep` are for the check: a fake session stands in for the
    network, and a fake sleep proves backoff without waiting."""
    env = os.environ if env is None else env
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.func is _send:
            _send(args, env=env, session=session)
        elif args.func is _media:
            _media(args, env=env, session=session)
        elif args.func is _recv:
            _recv(args, env=env, session=session, **({"sleep": sleep} if sleep else {}))
        else:
            args.func(args)
    except WhatsAppError as exc:
        return _fail(exc, exc.code, env)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 — nothing may reach a caller as a traceback
        return _fail(exc, classify(exc), env)
    return 0


def _errors(args):
    """Print the code table from the installed package — always the version running."""
    rows = sorted(CODES.items(), key=lambda item: item[1].exit_status)
    width = max(len(name) for name, _ in rows)
    print(f"{'CODE'.ljust(width)}  EXIT  RETRY  MEANING")
    for name, entry in rows:
        retry = "yes" if entry.retry else "no"
        print(f"{name.ljust(width)}  {str(entry.exit_status).rjust(4)}  {retry.ljust(5)}  {entry.message}")
    print("\nExit 130 is Ctrl-C, not a failure. Full table with what to do about each:")
    print("https://github.com/mhmzdev/whatsapp-agent-cli/blob/main/docs/errors.md")


def _fail(exc, code, env):
    message = CODES[code].message if code in CODES else str(exc)
    detail = getattr(exc, "detail", "") or str(exc)
    # The code in brackets is what docs/errors.md is keyed by: something a user can
    # search for, quote in an issue, or grep out of a log.
    print(f"error [{code}]: {message}", file=sys.stderr)
    if detail and detail != message:
        print(f"detail: {detail}", file=sys.stderr)
    if (env.get(DEBUG_ENV) or "").strip() not in ("", "0"):
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return exit_status(code)


if __name__ == "__main__":
    sys.exit(main())
