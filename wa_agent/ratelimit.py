"""One rolling window per platform method.

The platform publishes a separate per-minute budget for each method — 15 polls,
12 sends, 12 status calls, 12 media calls — each its own rolling 60s counter,
scoped per agent. Pacing proactively is cheaper than discovering the limit: a
429 costs a round trip and, on the poll endpoint, a cursor you then have to
reason about.

`now` and `sleep` are injected so a test can prove the pacing without waiting.
"""

import time

# Platform manual v1, "Rate limits". Each is its own rolling window.
DEFAULT_LIMITS = {
    "messages": 12,   # POST /messages
    "statuses": 12,   # POST /statuses (read receipts, typing)
    "updates": 15,    # GET /updates (the poll loop)
    "media_post": 12,  # POST /media — upload
    "media_get": 12,   # GET /media — metadata and download
}
WINDOW_SECONDS = 60


class RateLimiter:
    """`acquire` blocks until a call would not exceed the method's limit.

    `penalize` marks a window fully spent as of now, so the next `acquire` waits
    until it can plausibly have reset instead of guessing a flat delay — which is
    what a 429 means: the platform's count and ours disagree, and the platform is
    right.
    """

    def __init__(self, limits=None, window=WINDOW_SECONDS, now=time.time, sleep=time.sleep):
        self._limits = {**DEFAULT_LIMITS, **(limits or {})}
        self._window = window
        self._now = now
        self._sleep = sleep
        self._calls = {method: [] for method in self._limits}

    def _drop_expired(self, method, t):
        calls = self._calls[method]
        cutoff = t - self._window
        while calls and calls[0] <= cutoff:
            calls.pop(0)

    def acquire(self, method):
        limit = self._limits.get(method)
        if not limit:
            return
        calls = self._calls[method]
        while True:
            t = self._now()
            self._drop_expired(method, t)
            if len(calls) < limit:
                calls.append(t)
                return
            self._sleep(calls[0] + self._window - t)

    def penalize(self, method):
        """Treat this method's window as fully spent right now (a 429 arrived)."""
        limit = self._limits.get(method)
        if not limit:
            return
        self._calls[method] = [self._now()] * limit
