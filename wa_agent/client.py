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
from pathlib import Path

from . import media as media_types
from .errors import AuthError, WhatsAppError
from .ratelimit import DEFAULT_LIMITS, RateLimiter
from .text import DEFAULT_CHUNK, chunks, numbered, to_whatsapp

BASE = "https://api.whatsapp.com/agent/v1"
RETRYABLE_STATUS = (408, 425, 429, 500, 502, 503, 504)
MAX_POLL_TIMEOUT = 25   # the platform's own ceiling on the long-poll

# What `probe_token` asks, and which answers it reads as "the token is good". UNCONFIRMED
# against the live platform: the guess is that a good token gets a 404 for a media id
# that cannot exist, and a dead one a 401 or a 400 with error.code 100. Both constants
# are set from the post-merge probe (docs/exec-plans, GH-32). The id matters: a 400 with
# error.code 100 is also what a *malformed* id can earn with a good token, and the rule
# below would then call that good token dead.
PROBE_MEDIA_ID = "1"
PROBE_ACCEPTED = (404,)

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
            import requests  # imported lazily so `import wa_agent` stays cheap

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
        if status == 409:
            # A newer poll replaced ours. One poller per token is a platform rule,
            # and two of them steal messages from each other silently.
            raise WhatsAppError("another_poller", detail)
        if status in RETRYABLE_STATUS:
            raise WhatsAppError("platform_unavailable", detail)
        if 400 <= status < 500:
            raise WhatsAppError("platform_rejected", detail)
        raise WhatsAppError("platform_unavailable", detail)

    def poll(self, offset=None, limit=50, timeout=20, replay=False):
        """One long-poll. Returns `(messages, next_offset)`.

        No offset and `replay=False` asks for new traffic only — the platform sends
        nothing older, which is what a first run wants. `replay=True` sends
        `offset=0`, which replays what the platform still holds (30 days).
        A 204 means the poll timed out with nothing to deliver: an empty batch, and
        the caller keeps the offset it had.
        """
        params = {"limit": int(limit), "timeout": min(int(timeout), MAX_POLL_TIMEOUT)}
        if offset:
            params["offset"] = offset
        elif replay:
            params["offset"] = 0
        response = self._request("updates", "GET", "/updates", params=params,
                                 timeout=min(int(timeout), MAX_POLL_TIMEOUT) + 10)
        if response.status_code == 204:
            return [], offset
        try:
            body = response.json() or {}
        except Exception:  # noqa: BLE001 — a 2xx with an unreadable body is an empty batch
            return [], offset
        messages = []
        for entry in body.get("entry") or []:
            for change in entry.get("changes") or []:
                messages.extend((change.get("value") or {}).get("messages") or [])
        return messages, body.get("next_offset") or offset

    def typing(self, message_id):
        """Mark a message read and show the typing indicator.

        Never raises: a receipt that fails is cosmetic, and losing the message it
        refers to because of it would not be. Returns True when the platform took it.
        """
        try:
            self._request("statuses", "POST", "/statuses", json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
                "typing_indicator": {"type": "text"},
            }, timeout=10)
            return True
        except WhatsAppError:
            return False

    def download(self, media_id, dest_dir):
        """Fetch media in the platform's two hops: metadata, then the bytes.

        Written to a temp name and renamed only once the body is complete, so a
        failure never leaves a half-file that looks downloaded. Returns
        `(path, mime)`.
        """
        meta = self._request("media_get", "GET", f"/media/{media_id}", timeout=30)
        try:
            info = meta.json() or {}
        except Exception as exc:  # noqa: BLE001
            raise WhatsAppError("platform_rejected", f"media {media_id}: metadata was not JSON") from exc
        url = info.get("url")
        if not url:
            raise WhatsAppError("platform_rejected", f"media {media_id}: metadata carried no url")
        mime = info.get("mime_type", "")

        self.limits.acquire("media_get")
        try:
            response = self._session.request("GET", url, headers=self._headers, timeout=60)
        except self._transport_errors as exc:
            raise WhatsAppError("platform_unavailable", f"media {media_id}: {exc}") from exc
        if response.status_code == 404:
            # The url is short-lived; the media id is not. Re-fetching is the fix.
            raise WhatsAppError("media_url_expired", f"media {media_id}: HTTP 404 on the download url")
        self._checked(response, "GET", f"media {media_id} bytes")

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{media_id}{media_types.extension_for(mime)}"
        tmp = path.with_name(path.name + ".part")
        try:
            tmp.write_bytes(response.content)
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return path, mime

    def probe_token(self):
        """Ask the platform whether it accepts this token, without disturbing anything.

        Never `/updates`: a poll from here would take the long-poll away from a running
        `recv` and hand it a 409, so checking the token would break the thing it checks.
        It is one `GET /media/<id>` for an id that cannot exist — a read, with no side
        effect. The answer is classified here rather than through `_checked`, because
        `_checked` folds every 4xx into one code and this has to tell "404: the token is
        fine, the id is not" from "403: something this does not understand".

        Returns True when the token is accepted. Raises `AuthError` when it is dead,
        `platform_unavailable` when nothing could be learned (worth retrying), and
        `platform_rejected` when the platform said something the mapping does not know,
        which must never be reported as a good token. The mapping is unconfirmed until
        the post-merge probe; see PROBE_MEDIA_ID.
        """
        path = f"/media/{PROBE_MEDIA_ID}"
        self.limits.acquire("media_get")
        try:
            response = self._session.request("GET", f"{self.base}{path}", headers=self._headers, timeout=15)
        except self._transport_errors as exc:
            raise WhatsAppError("platform_unavailable", f"GET {path}: {exc}") from exc

        status = response.status_code
        if 200 <= status < 300 or status in PROBE_ACCEPTED:
            return True
        code = _error_code(response)
        detail = f"GET {path}: HTTP {status}{f' error.code {code}' if code else ''} {_body_excerpt(response)}".strip()
        if status == 401 or (status == 400 and code == 100):
            raise AuthError(detail)
        if status in RETRYABLE_STATUS or status >= 500:
            raise WhatsAppError("platform_unavailable", detail)
        raise WhatsAppError("platform_rejected", detail)

    def upload(self, path, mime=None):
        """Upload a local file, returning its media id.

        The size cap is checked here rather than by the platform: a refusal costs
        one of twelve requests a minute, and the answer is knowable locally.
        """
        path = Path(path)
        if not path.is_file():
            raise WhatsAppError("bad_usage", f"{path} is not a file")
        mime = mime or media_types.guess_type(path)
        if not mime:
            raise WhatsAppError("bad_usage", f"cannot tell the type of {path.name}; pass --type")
        size = path.stat().st_size
        cap = media_types.cap_for(mime)
        if size > cap:
            raise WhatsAppError("media_too_large",
                                f"{path.name} is {size // 1024} KB; the cap for {mime} is {cap // 1024} KB")
        with path.open("rb") as handle:
            response = self._request("media_post", "POST", "/media",
                                     files={"file": (path.name, handle, mime)},
                                     data={"messaging_product": "whatsapp", "type": mime},
                                     timeout=60)
        try:
            media_id = (response.json() or {}).get("id")
        except Exception:  # noqa: BLE001
            media_id = None
        if not media_id:
            raise WhatsAppError("platform_rejected", f"upload of {path.name} returned no media id")
        return media_id

    def send_media(self, to, media_id, caption=None, filename=None, mime=None):
        """Attach an uploaded file to a message. Returns one `Sent`.

        A caption is not chunked: the platform's caption limit is far below a text
        body's, and quietly splitting an attachment's caption across messages would
        be worse than letting the platform refuse it.
        """
        if not to:
            raise WhatsAppError("no_recipient", "send_media called without a recipient")
        kind = media_types.kind_for(mime)
        payload = {"id": media_id}
        if caption:
            payload["caption"] = to_whatsapp(caption)
        if kind == "document" and filename:
            payload["filename"] = filename
        response = self._request("messages", "POST", "/messages", json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": kind,
            kind: payload,
        }, timeout=30)
        return Sent(_sent_id(response), payload.get("caption") or f"<{kind} {media_id}>")

    def parts_for(self, text):
        """What `send` would put on the wire: converted, split, numbered."""
        return numbered(chunks(to_whatsapp(text), self.chunk_chars))

    def send_iter(self, to, text):
        """Yield a `Sent(id, text)` as each part leaves, so a caller learns about a
        delivered part **before** a later one can fail.

        A multi-part send has no transaction behind it: if part three is refused,
        parts one and two are already on someone's phone. Returning only at the end
        would throw that knowledge away with the exception, leaving the caller to
        retry and duplicate what already arrived.

        Parts are not spaced by a sleep: the rate limiter already paces sends at the
        platform's 12/min, and an extra second per part would double the wall clock
        of a long reply for no benefit.
        """
        if not to:
            raise WhatsAppError("no_recipient", "send called without a recipient")
        for part in self.parts_for(text):
            response = self._request("messages", "POST", "/messages", json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": part},
            }, timeout=30)
            yield Sent(_sent_id(response), part)

    def send(self, to, text):
        """Send one text, split under the cap. Returns a `Sent(id, text)` per part.

        The eager form of `send_iter`, for a caller that does not care which parts
        made it when one fails.
        """
        return list(self.send_iter(to, text))


def _sent_id(response):
    """The id the platform assigned, or a local stand-in so a caller always has a key."""
    try:
        body = response.json() or {}
    except Exception:  # noqa: BLE001
        body = {}
    messages = body.get("messages") or [{}]
    return messages[0].get("id") or body.get("id") or f"out:{int(time.time() * 1000)}"
