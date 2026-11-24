"""Progress of the long-running syncs, for the sidebar's progress bar.

Code doing the work (on a background thread) reports into a Stage; the UI
polls current() on a timer — so the models need no Qt and no signals:

    with progress.stage("Collection", total=1, step_seconds=moxfield.REQUEST_INTERVAL) as s:
        ...                       # first page
        s.update(1, total=35)     # now the total is known
        s.update(2)               # ...

current() returns the most recently started stage still running (or None).
step_seconds: how long one step takes at least (e.g. Moxfield's request
spacing) — used for the time-left estimate until real timings exist.
"""

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Stage:
    name: str
    total: int
    done: int = 0
    step_seconds: float = 0.0
    started: float = field(default_factory=time.monotonic)

    def update(self, done: int, total: int | None = None):
        with _lock:
            if total is not None:
                self.total = max(total, 0)
            self.done = max(0, min(done, self.total)) if self.total else done

    def advance(self, steps: int = 1):
        self.update(self.done + steps)

    def seconds_left(self) -> float | None:
        """Estimated seconds to go: from the pace so far (once a step is
        done), never less than the remaining steps at step_seconds each."""
        left = self.total - self.done
        if left <= 0:
            return 0.0
        floor = left * self.step_seconds
        if self.done:
            pace = (time.monotonic() - self.started) / self.done
            return max(floor, pace * left)
        return floor or None

    def text(self) -> str:
        """e.g. "Collection pages: 3 of 35" + a line "about 40 s left"."""
        text = f"{self.name}: {self.done} of {self.total}" if self.total else f"{self.name}…"
        left = self.seconds_left()
        if left:
            text += f"\nabout {_duration(left)} left"
        return text


_lock = threading.Lock()
_stages: list[Stage] = []


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{max(seconds, 1)} s"
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds < 600 else f"{round(seconds / 60)} min"


@contextmanager
def stage(name: str, total: int = 0, step_seconds: float = 0.0):
    """A unit of work shown while the with-block runs."""
    s = Stage(name, total, step_seconds=step_seconds)
    with _lock:
        _stages.append(s)
    try:
        yield s
    finally:
        with _lock:
            if s in _stages:
                _stages.remove(s)


def current() -> Stage | None:
    """The stage to show: the latest one still running."""
    with _lock:
        return _stages[-1] if _stages else None


def snapshot() -> tuple[str, int, int] | None:
    """(text, done, total) of current(), read consistently — for the UI."""
    s = current()
    if s is None:
        return None
    with _lock:
        done, total = s.done, s.total
    return s.text(), done, total
