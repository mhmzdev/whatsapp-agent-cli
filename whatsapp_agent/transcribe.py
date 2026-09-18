"""Voice notes to text.

Gemini takes audio inline in an ordinary JSON request, so this needs nothing but
the `requests` the package already depends on — no provider SDK, and the whole
path is drivable by the same injected fake session the rest of the package uses
in its tests.

The key comes from the environment (`GEMINI_API_KEY` by default), never from a
config file and never from a flag, so it does not end up in a shell history or a
process listing.
"""

import base64
import os
from pathlib import Path

from .errors import WhatsAppError

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_KEY_ENV = "GEMINI_API_KEY"
PROVIDERS = ("gemini",)

# Keep what was said, in the language it was said in. A transcript that quietly
# translates is worse than no transcript: nobody can tell it happened.
PROMPT = (
    "Transcribe this voice note exactly as spoken. Keep the language as is: English stays "
    "English, Urdu may be written in Urdu script or Roman Urdu as the speaker would type it. "
    "Numbers as digits. Output only the transcript, with no preamble and no commentary. "
    "If nothing intelligible is said, output exactly: [inaudible]"
)

# Gemini needs a mime type for inline audio, and WhatsApp's voice notes are ogg.
MIME_BY_EXT = {
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
    ".mp3": "audio/mpeg", ".amr": "audio/amr", ".wav": "audio/wav",
    ".flac": "audio/flac",
}

RETRYABLE_STATUS = (408, 425, 429, 500, 502, 503, 504)


def api_key(key_env=DEFAULT_KEY_ENV, env=None):
    """The transcription key, or None. Separate so a caller can warn once, up
    front, rather than discovering it per voice note."""
    env = os.environ if env is None else env
    return (env.get(key_env) or "").strip() or None


def mime_for(path):
    return MIME_BY_EXT.get(Path(path).suffix.lower())


def transcribe(path, *, model=None, key_env=DEFAULT_KEY_ENV, language=None,
               provider="gemini", session=None, env=None, timeout=120):
    """Audio file in, text out. Raises a coded failure, never a partial transcript.

    An empty answer is a failure, not an empty transcript: hisab learned that the
    hard way when a provider's error text was handed to a model as if it were
    something the user had said.
    """
    if provider not in PROVIDERS:
        raise WhatsAppError("bad_usage",
                            f"unknown transcription provider {provider!r}; this release has {', '.join(PROVIDERS)}"
                            " (offline transcription is issue #20)")
    path = Path(path)
    if not path.is_file():
        raise WhatsAppError("bad_usage", f"{path} is not a file")
    mime = mime_for(path)
    if not mime:
        raise WhatsAppError("bad_usage", f"{path.suffix or 'that file'} is not an audio type this can read")

    key = api_key(key_env, env=env)
    if not key:
        raise WhatsAppError("no_transcription_key", f"{key_env} is not set")

    prompt = PROMPT if not language else f"{PROMPT} The speaker is using {language}."
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(path.read_bytes()).decode()}},
        {"text": prompt},
    ]}]}
    url = GEMINI_URL.format(model=model or DEFAULT_MODEL)

    if session is None:
        import requests

        session = requests.Session()
        transport_errors = (requests.RequestException,)
    else:
        transport_errors = tuple(getattr(session, "transport_errors", ()) or ())

    try:
        response = session.request("POST", url, headers={"x-goog-api-key": key,
                                                         "Content-Type": "application/json"},
                                   json=body, timeout=timeout)
    except transport_errors as exc:
        raise WhatsAppError("transcription_unavailable", f"transcription request failed: {exc}") from exc

    status = response.status_code
    if status in RETRYABLE_STATUS:
        raise WhatsAppError("transcription_unavailable", f"transcription: HTTP {status}")
    if status // 100 != 2:
        raise WhatsAppError("transcription_failed", f"transcription: HTTP {status} {_excerpt(response)}")

    return _text_of(response)


def _text_of(response):
    try:
        body = response.json() or {}
    except Exception as exc:  # noqa: BLE001
        raise WhatsAppError("transcription_failed", "transcription returned a body that was not JSON") from exc
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        # A refusal or a safety block answers 200 with no candidate. Returning
        # whatever is in the body would hand an error message on as speech.
        raise WhatsAppError("transcription_failed", f"transcription returned no text: {str(body)[:200]}") from None
    text = (text or "").strip()
    if not text:
        raise WhatsAppError("transcription_failed", "transcription returned an empty transcript")
    return text


def _excerpt(response, limit=200):
    try:
        return (response.text or "")[:limit].replace("\n", " ").strip()
    except Exception:  # noqa: BLE001
        return ""
