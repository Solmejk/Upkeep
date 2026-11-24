"""RateLimiter: keeps requests to an online service at a fixed pace,
across every thread of the app. Used by scryfall.py (2 per second) and
moxfield.py (Moxfield's strict 1 per second).
"""

import threading
import time


class RateLimiter:
    """Throttles calls to at most one per `interval` seconds, shared
    across threads: however many threads are waiting, the requests they
    send still land no closer together than that. Services ban IPs that
    go over their limits, so this is not optional."""

    def __init__(self, max_per_second: float | None = None, *, interval: float | None = None):
        """Give either max_per_second or interval (seconds between calls)."""
        if interval is None:
            interval = 1.0 / max_per_second
        self._interval = interval
        self._lock = threading.Lock()
        self._next_slot = 0.0

    @property
    def interval(self) -> float:
        return self._interval

    def wait(self):
        """Blocks the calling thread until its turn: call immediately
        before each outbound request."""
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_slot)
            self._next_slot = start + self._interval
            delay = start - now
        if delay > 0:
            time.sleep(delay)
