"""The command-line front door. Every subcommand is a thin wrapper over the
library; the library is what hisab-whatsapp and anything else import.

argparse rather than click or typer: a transport library that pushes a CLI
framework into every dependent's environment is a worse library, and this
surface is small enough that the standard library covers it.

The subcommands below parse their arguments and then fail with
`not_implemented` until their own ticket lands — #5 recv, #6 media, #7
transcribe. They exit non-zero on purpose: a stub that exits 0 would make an
unimplemented command look like a passing one.
"""

import argparse
import os
import sys
import traceback

from . import __version__
from .client import WhatsApp
from .errors import CODES, WhatsAppError, classify, exit_status
from .state import DEFAULT_PROFILE, TOKEN_ENV, resolve_token, state_dir
from .store import Store
from .text import DEFAULT_CHUNK, chunks, numbered, to_whatsapp

DEBUG_ENV = "WHATSAPP_AGENT_DEBUG"


def _todo(command, issue):
    raise WhatsAppError("not_implemented", f"{command} lands in #{issue}")


def _send(args, env=None, session=None):
    """Send one text. Recipient: --to, else the creator recv recorded (#5)."""
    directory = state_dir(args.profile, args.state_dir, env=env)
    store = Store(directory)
    to = args.to or store.creator()
    if not to:
        raise WhatsAppError("no_recipient", "no --to and no creator recorded yet")

    if args.dry_run:
        # Rehearse a long message without spending one: the same conversion and
        # split the wire would see, no call, no store record, no token needed.
        for part in numbered(chunks(to_whatsapp(args.text), DEFAULT_CHUNK)):
            print(part)
            print("---")
        return

    client = WhatsApp(resolve_token(args.token_file, env=env), session=session)
    for sent in client.send(to, args.text):
        store.add(sent.id, "out", sent.text)
        print(sent.id)


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
    p_send.add_argument("text", help="the message body; split under the platform cap")
    p_send.add_argument("--to", metavar="USER", help="recipient id (default: the creator recv recorded)")
    p_send.add_argument("--dry-run", action="store_true", help="print the parts that would be sent, send nothing")
    p_send.set_defaults(func=_send)

    p_recv = sub.add_parser("recv", help="read new messages since the stored cursor")
    p_recv.add_argument("--follow", action="store_true", help="hold the long-poll open and stream")
    p_recv.add_argument("--json", action="store_true", help="one JSON object per line")
    p_recv.add_argument("--transcribe", action="store_true", help="replace a voice note with its transcript")
    p_recv.add_argument("--limit", type=int, default=50, metavar="N", help="messages per poll (default: %(default)s)")
    p_recv.set_defaults(func=lambda args: _todo("recv", 5))

    p_media = sub.add_parser("media", help="download or upload media")
    media_sub = p_media.add_subparsers(dest="media_command", metavar="<get|put>", required=True)
    p_get = media_sub.add_parser("get", help="download media by id")
    p_get.add_argument("media_id")
    p_get.add_argument("--out", metavar="DIR", help="directory to write into (default: the state dir)")
    p_get.set_defaults(func=lambda args: _todo("media get", 6))
    p_put = media_sub.add_parser("put", help="upload a file and print its media id")
    p_put.add_argument("path")
    p_put.add_argument("--type", metavar="MIME", help="content type (default: guessed from the extension)")
    p_put.set_defaults(func=lambda args: _todo("media put", 6))

    p_tr = sub.add_parser("transcribe", help="turn an audio file into text")
    p_tr.add_argument("path")
    p_tr.set_defaults(func=lambda args: _todo("transcribe", 7))

    return parser


def main(argv=None, env=None, session=None):
    """`session` is for the check: any object with `.request` stands in for the network."""
    env = os.environ if env is None else env
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.func is _send:
            _send(args, env=env, session=session)
        else:
            args.func(args)
    except WhatsAppError as exc:
        return _fail(exc, exc.code, env)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 — nothing may reach a caller as a traceback
        return _fail(exc, classify(exc), env)
    return 0


def _fail(exc, code, env):
    message = CODES[code].message if code in CODES else str(exc)
    detail = getattr(exc, "detail", "") or str(exc)
    print(f"error: {message}", file=sys.stderr)
    if detail and detail != message:
        print(f"detail: {detail}", file=sys.stderr)
    if (env.get(DEBUG_ENV) or "").strip() not in ("", "0"):
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return exit_status(code)


if __name__ == "__main__":
    sys.exit(main())
