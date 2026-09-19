"""Voice notes to text.

Two providers over plain HTTP, so they need nothing but the `requests` the
package already depends on — no provider SDK, and the whole path is drivable by the
same injected fake session the rest of the package uses in its tests. Gemini takes
the audio inline in a JSON request; OpenRouter takes it as a multipart upload to
its transcription endpoint. A third, `local`, runs Whisper on this machine through
the optional `faster-whisper` extra (see `local.py`): no key, no network, and a
different failure mode, which is why it is never chosen for the caller.

The provider is always the caller's choice, `gemini` unless told otherwise. It
is never worked out from which key happens to be set, and never from which key is
missing: a key exported for something else must not be spent because it was lying
in the environment, and a weaker offline engine must not stand in for a provider
whose key was forgotten.

The key comes from the environment (the chosen provider's own variable by
default), never from a config file and never from a flag, so it does not end up
in a shell history or a process listing. `local` has none.
"""

import base64
import os
from pathlib import Path

from . import local
from .errors import WhatsAppError

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_KEY_ENV = "GEMINI_API_KEY"
KEYED_PROVIDERS = ("gemini", "openrouter")
PROVIDERS = KEYED_PROVIDERS + ("local",)

# One row per keyed provider: the variable its key is read from. `local` has no row on
# purpose: it has no key, and a row of `None` would make every reader handle a hole.
KEY_ENVS = {"gemini": DEFAULT_KEY_ENV, "openrouter": "OPENROUTER_API_KEY"}
# The model used when the caller names none. OpenRouter's ids are namespaced by the
# model's maker; for `local` it is a size (`tiny`, `base`, `small`).
MODELS = {"gemini": DEFAULT_MODEL, "openrouter": "openai/whisper-1", "local": local.DEFAULT_SIZE}

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


def key_env_for(provider, override=None):
    """The variable a provider's key is read from: the caller's `--key-env` if given.
    `None` for a provider with no key."""
    return override or KEY_ENVS.get(provider)


def model_for(provider, override=None):
    return override or MODELS[provider]


def check_provider(provider):
    """Refuse an unknown provider. Separate so `recv` can do it before it polls,
    rather than marking every voice note failed for the rest of a `--follow`."""
    if provider not in PROVIDERS:
        raise WhatsAppError("bad_usage",
                            f"unknown transcription provider {provider!r}; this release has {', '.join(PROVIDERS)}")


def check_usage(provider, key_env=None, model=None):
    """Refuse a combination that can never work, before anything is polled or read.
    `local` takes no key and a model that is a size; a mistake in either would
    otherwise be reported once per voice note for as long as a `--follow` runs."""
    check_provider(provider)
    if provider == "local":
        if key_env:
            raise WhatsAppError("bad_usage", "--key-env does not apply to --provider local: it needs no key")
        local.check_size(model_for(provider, model))


def mime_for(path):
    return MIME_BY_EXT.get(Path(path).suffix.lower())


def transcribe(path, *, model=None, key_env=None, language=None,
               provider="gemini", session=None, env=None, timeout=120):
    """Audio file in, text out. Raises a coded failure, never a partial transcript.

    `key_env` names the variable holding the key; left out, it is the provider's
    own (`GEMINI_API_KEY`, `OPENROUTER_API_KEY`). `local` has no key and refuses
    one; its `model` is a size, and its model must already have been downloaded
    (`wa-agent model pull`): a transcription never downloads.

    An empty answer is a failure, not an empty transcript: hisab learned that the
    hard way when a provider's error text was handed to a model as if it were
    something the user had said.
    """
    check_usage(provider, key_env, model)
    path = Path(path)
    if not path.is_file():
        raise WhatsAppError("bad_usage", f"{path} is not a file")
    mime = mime_for(path)
    if not mime:
        raise WhatsAppError("bad_usage", f"{path.suffix or 'that file'} is not an audio type this can read")

    if provider == "local":
        return _nonempty(local.run(path, model_for(provider, model), language, env=env))

    key_name = key_env_for(provider, key_env)
    key = api_key(key_name, env=env)
    if not key:
        raise WhatsAppError("no_transcription_key", f"{key_name} is not set")

    if session is None:
        import requests

        session = requests.Session()
        transport_errors = (requests.RequestException,)
    else:
        transport_errors = tuple(getattr(session, "transport_errors", ()) or ())

    try:
        if provider == "gemini":
            response = _gemini_request(session, path, mime, key, model, language, timeout)
        else:
            response = _openrouter_request(session, path, key, model, language, timeout)
    except transport_errors as exc:
        raise WhatsAppError("transcription_unavailable", f"transcription request failed: {exc}") from exc

    status = response.status_code
    if status in RETRYABLE_STATUS:
        raise WhatsAppError("transcription_unavailable", f"transcription: HTTP {status}")
    if status // 100 != 2:
        raise WhatsAppError("transcription_failed", f"transcription: HTTP {status} {_excerpt(response)}")

    return _gemini_text(response) if provider == "gemini" else _openrouter_text(response)


def _gemini_request(session, path, mime, key, model, language, timeout):
    prompt = PROMPT if not language else f"{PROMPT} The speaker is using {language}."
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(path.read_bytes()).decode()}},
        {"text": prompt},
    ]}]}
    url = GEMINI_URL.format(model=model_for("gemini", model))
    return session.request("POST", url, headers={"x-goog-api-key": key,
                                                 "Content-Type": "application/json"},
                           json=body, timeout=timeout)


def _openrouter_request(session, path, key, model, language, timeout):
    """Multipart, as the endpoint expects. The file goes as bytes so nothing is left
    open if the request fails, and with no mime type: the extension names the format.
    `language` is sent as given — a Whisper-style endpoint wants a code such as `ur`,
    not the word the Gemini prompt takes."""
    data = {"model": model_for("openrouter", model)}
    if language:
        data["language"] = language
    return session.request("POST", OPENROUTER_URL, headers={"Authorization": f"Bearer {key}"},
                           data=data, files={"file": (path.name, path.read_bytes())}, timeout=timeout)


def _json_body(response):
    try:
        return response.json() or {}
    except Exception as exc:  # noqa: BLE001
        raise WhatsAppError("transcription_failed", "transcription returned a body that was not JSON") from exc


def _gemini_text(response):
    body = _json_body(response)
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        # A refusal or a safety block answers 200 with no candidate. Returning
        # whatever is in the body would hand an error message on as speech.
        raise WhatsAppError("transcription_failed", f"transcription returned no text: {str(body)[:200]}") from None
    return _nonempty(text)


def _openrouter_text(response):
    body = _json_body(response)
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise WhatsAppError("transcription_failed", f"transcription returned no text: {str(body)[:200]}")
    return _nonempty(body["text"])


def _nonempty(text):
    text = (text or "").strip()
    if not text:
        raise WhatsAppError("transcription_failed", "transcription returned an empty transcript")
    return text


def _excerpt(response, limit=200):
    try:
        return (response.text or "")[:limit].replace("\n", " ").strip()
    except Exception:  # noqa: BLE001
        return ""
