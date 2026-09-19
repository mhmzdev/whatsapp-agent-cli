"""A client for the WhatsApp Agent Platform — library first, with a CLI on top.

    import wa_agent            # from Python
    wa-agent send "hello"      # from a shell

This package owns the transport and nothing else: tokens, the poll cursor, the
message store, rate limits, the send cap, media and transcription. It knows
nothing about coding agents, folders, permissions, sessions or models.
"""

from importlib.metadata import PackageNotFoundError, version as _version

from .client import Sent, WhatsApp
from .errors import CODES, AuthError, WhatsAppError, classify
from .state import resolve_token, state_dir
from .store import Store

try:
    __version__ = _version("wa-agent")
except PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0+dev"

# The names a dependent imports. `requests` is still not imported until a
# WhatsApp client is actually constructed.
__all__ = [
    "__version__",
    "WhatsApp",
    "Sent",
    "Store",
    "AuthError",
    "WhatsAppError",
    "CODES",
    "classify",
    "resolve_token",
    "state_dir",
]
