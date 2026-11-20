"""Plain-text log of Moxfield syncs (cache/sync_log.txt), shown on the
Settings screen's Sync log page. One line per sync step, newest last:

    2026-11-17 23:41:05 | Collection | Collection page | Solmejk | OK     |   3.4s | 4434 cards (3352 unique)

Not touched by clearCache (it only removes the data caches).
"""

import time
from datetime import datetime

import paths

MAX_LINES = 500  # older lines are dropped so the file stays small


def logged(kind: str, source: str, username: str, fn):
    """Runs fn() (a sync step returning a short summary string, or None)
    and records the outcome. kind: what was synced ("Profile",
    "Collection", "Decks"). source: what triggered it ("Home", "Login",
    "Decks page", ...). Re-raises fn's exception after logging it."""
    start = time.monotonic()
    try:
        summary = fn()
    except Exception as e:
        _append(kind, source, username, "FAILED", time.monotonic() - start, str(e))
        raise
    _append(kind, source, username, "OK", time.monotonic() - start, summary or "")
    return summary


def read_lines() -> list[str]:
    """All log lines, oldest first (empty if nothing's been synced yet)."""
    if not paths.SYNC_LOG_PATH.exists():
        return []
    with open(paths.SYNC_LOG_PATH, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def last_success(kind: str) -> str | None:
    """Timestamp of the most recent successful sync of `kind`, or None."""
    for line in reversed(read_lines()):
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) >= 5 and parts[1] == kind and parts[4] == "OK":
            return parts[0]
    return None


def _append(kind, source, username, status, seconds, details):
    """Adds one line to the log, trimming it to the last MAX_LINES."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details = " ".join(details.split())  # error messages can span lines
    line = (
        f"{timestamp} | {kind:<10} | {source:<15} | {username} | "
        f"{status:<6} | {seconds:5.1f}s | {details}"
    )
    lines = (read_lines() + [line])[-MAX_LINES:]
    paths.SYNC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.SYNC_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
