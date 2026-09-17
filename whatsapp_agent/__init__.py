"""A client for the WhatsApp Agent Platform — library first, with a CLI on top.

    import whatsapp_agent            # from Python
    whatsapp-agent send "hello"      # from a shell

This package owns the transport and nothing else: tokens, the poll cursor, the
message store, rate limits, the send cap, media and transcription. It knows
nothing about coding agents, folders, permissions, sessions or models.
"""

from importlib.metadata import PackageNotFoundError, version as _version

from .errors import AuthError, WhatsAppError, classify

try:
    __version__ = _version("whatsapp-agent")
except PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0+dev"

__all__ = ["__version__", "AuthError", "WhatsAppError", "classify"]
