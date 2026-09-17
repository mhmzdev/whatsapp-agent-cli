"""The HTTP layer: one class over the platform's endpoints.

Every call goes through `_request`, which paces against the published rate
limits, retries once past a 429, and turns a response into one of three
outcomes: it worked, it will never work (`platform_rejected`, and `AuthError`
for the token itself), or it might work later (`platform_unavailable`). Callers
branch on that distinction and nothing else — a poll loop sleeps on the third
and exits on the second.

The session is injectable so the check can drive a fake one. Nothing here reads
the network unless a caller passes a real session or lets it default to
`requests`.
"""

import time
from collections import namedtuple

from .errors import AuthError, WhatsAppError
from .ratelimit import DEFAULT_LIMITS, RateLimiter
from .text import DEFAULT_CHUNK, chunks, numbered, to_whatsapp

BASE = "https://api.whatsapp.com/agent/v1"
RETRYABLE_STATUS = (408, 425, 429, 500, 502, 503, 504)

# One part of a sent message: the id the platform gave it, and the text it carries.
# Returning both means a caller never has to re-run the split to know what was sent.
Sent = namedtuple("Sent", "id text")


def _error_code(response):
    """The platform's own `error.code`, when the body carries one."""
    try:
        body = response.json() or {}
    except Exception:  # noqa: BLE001 — a non-JSON body is an answer in itself
        return None
    error = body.get("error")
    return error.get("code") if isinstance(error, dict) else None


def _body_excerpt(response, limit=300):
    """A short slice of the body for the operator's detail line. Never the headers,
    so a token cannot travel with it."""
    try:
        return (response.text or "")[:limit].replace("\n", " ").strip()
    except Exception:  # noqa: BLE001
        return ""


class WhatsApp:
    """A client for one agent token."""

    def __init__(self, token, session=None, limits=None, chunk_chars=DEFAULT_CHUNK,
                 now=time.time, sleep=time.sleep, base=BASE):
        if not token:
            raise WhatsAppError("no_token", "WhatsApp client built without a token")
        self._token = token
        self.base = base
        self.chunk_chars = int(chunk_chars)
        self.limits = RateLimiter({**DEFAULT_LIMITS, **(limits or {})}, now=now, sleep=sleep)
        if session is None:
            import requests  # imported lazily so `import whatsapp_agent` stays cheap

            session = requests.Session()
            self._transport_errors = (requests.RequestException,)
        else:
            self._transport_errors = tuple(getattr(session, "transport_errors", ()) or ())
        self._session = session

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method, verb, path, **kwargs):
        """One rate-limited call, retried once past a 429.

        `penalize` after the 429 means the retry's `acquire` waits until the
        window can plausibly have reset, rather than hammering a guessed delay.
        """
        url = f"{self.base}{path}"
        last = None
        for attempt in (1, 2):
            self.limits.acquire(method)
            try:
                response = self._session.request(verb, url, headers=self._headers, **kwargs)
            except self._transport_errors as exc:
                raise WhatsAppError("platform_unavailable", f"{verb} {path}: {exc}") from exc
            last = response
            if response.status_code == 429 and attempt == 1:
                self.limits.penalize(method)
                continue
            break
        return self._checked(last, verb, path)

    def _checked(self, response, verb, path):
        status = response.status_code
        if 200 <= status < 300:
            return response
        code = _error_code(response)
        where = f"{verb} {path}: HTTP {status}"
        detail = f"{where}{f' error.code {code}' if code else ''} {_body_excerpt(response)}".strip()
        if status == 401 or (status == 400 and code == 100):
            raise AuthError(detail)
        if status in RETRYABLE_STATUS:
            raise WhatsAppError("platform_unavailable", detail)
        if 400 <= status < 500:
            raise WhatsAppError("platform_rejected", detail)
        raise WhatsAppError("platform_unavailable", detail)

    def parts_for(self, text):
        """What `send` would put on the wire: converted, split, numbered."""
        return numbered(chunks(to_whatsapp(text), self.chunk_chars))

    def send(self, to, text):
        """Send one text, split under the cap. Returns a `Sent(id, text)` per part.

        Parts are not spaced by a sleep: the rate limiter already paces sends at
        the platform's 12/min, and an extra second per part would double the wall
        clock of a long reply for no benefit.
        """
        if not to:
            raise WhatsAppError("no_recipient", "send called without a recipient")
        sent = []
        for part in self.parts_for(text):
            response = self._request("messages", "POST", "/messages", json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": part},
            }, timeout=30)
            sent.append(Sent(_sent_id(response), part))
        return sent


def _sent_id(response):
    """The id the platform assigned, or a local stand-in so a caller always has a key."""
    try:
        body = response.json() or {}
    except Exception:  # noqa: BLE001
        body = {}
    messages = body.get("messages") or [{}]
    return messages[0].get("id") or body.get("id") or f"out:{int(time.time() * 1000)}"
