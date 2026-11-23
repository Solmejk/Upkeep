"""Session logs: everything that would show in a terminal, also written
to <your folder>/logs (files/logs from source, %APPDATA%/Upkeep/logs for
the built app — which has no terminal at all, so this is the only place
its output goes).

    logs/current.log   this session
    logs/previous.log  the session before (each start moves current there,
                       replacing the older one — so only two are ever kept)
    logs/current-<n>.log  a second window's, while the first is still open
                       (removed by the next normal start)

start() (called first thing by main.py) copies into current.log, each line
timestamped:
    print() output and anything else on stdout / stderr,
    uncaught Python errors (main thread, Qt slots, background threads),
    Qt's own warnings (qWarning etc., which bypass Python's stderr),
    hard crashes (faulthandler's traceback of every thread).
"""

import atexit
import faulthandler
import os
import platform
import sys
import threading
from datetime import datetime

import paths

LOGS_DIR = paths.LOGS_DIR
CURRENT_LOG = LOGS_DIR / "current.log"
PREVIOUS_LOG = LOGS_DIR / "previous.log"

_file = None
_lock = threading.Lock()


class _Tee:
    """Stands in for sys.stdout / sys.stderr: writes go to the terminal as
    before (if there is one) and to the log, with a timestamp at the start
    of each line."""

    def __init__(self, original, label: str):
        self._original = original  # None in the windowed .exe
        self._label = label
        self._line_start = True

    def write(self, text: str) -> int:
        if self._original is not None:
            try:
                self._original.write(text)
            except (OSError, ValueError):
                pass
        _write(text, self)
        return len(text)

    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except (OSError, ValueError):
                pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self):
        return "utf-8"


def _write(text: str, stream: "_Tee | None" = None, label: str = ""):
    """Appends text to the log, timestamping each new line."""
    if _file is None or not text:
        return
    with _lock:
        out = []
        for piece in text.splitlines(keepends=True):
            starts_line = stream._line_start if stream is not None else True
            if starts_line:
                tag = stream._label if stream is not None else label
                out.append(f"{datetime.now():%H:%M:%S}{' ' + tag if tag else ''}  ")
            out.append(piece)
            if stream is not None:
                stream._line_start = piece.endswith("\n")
        try:
            _file.write("".join(out))
            _file.flush()
        except (OSError, ValueError):
            pass


def _qt_message(mode, context, message):
    """Qt's warnings (they don't go through Python's stderr)."""
    from PySide6.QtCore import QtMsgType
    level = {QtMsgType.QtDebugMsg: "qt-debug", QtMsgType.QtInfoMsg: "qt-info",
             QtMsgType.QtWarningMsg: "qt-warning", QtMsgType.QtCriticalMsg: "qt-critical",
             QtMsgType.QtFatalMsg: "qt-fatal"}.get(mode, "qt")
    if sys.__stderr__ is not None:  # still on the terminal, as Qt would have
        try:
            sys.__stderr__.write(message + "\n")
        except (OSError, ValueError):
            pass
    _write(message + "\n", label=level)


def start():
    """Rotates the logs and starts copying this session into current.log.
    Never stops the app from starting: if the folder isn't writable,
    there's just no log."""
    global _file
    from version import VERSION
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        (paths.USER_ROOT / "crash.log").unlink(missing_ok=True)  # replaced by these logs
    except OSError:
        return
    try:
        if CURRENT_LOG.exists():
            CURRENT_LOG.replace(PREVIOUS_LOG)
        for extra in LOGS_DIR.glob("current-*.log"):  # second windows' logs from before
            extra.unlink(missing_ok=True)
        log_path = CURRENT_LOG
    except OSError:
        # current.log is still open: Upkeep is already running in another
        # window. This one logs to its own file instead of not at all.
        log_path = LOGS_DIR / f"current-{os.getpid()}.log"
    try:
        _file = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        _file = None
        return

    _file.write(f"Upkeep {VERSION} ({'installed / packaged' if paths.FROZEN else 'from source'}) — "
                f"session started {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"Python {platform.python_version()} · {platform.platform()} · data folder {paths.USER_ROOT}\n\n")
    _file.flush()

    sys.stdout = _Tee(sys.stdout, "")
    sys.stderr = _Tee(sys.stderr, "err")
    faulthandler.enable(file=_file, all_threads=True)  # hard crashes (segfaults etc.)

    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message)
    except ImportError:
        pass

    def _thread_error(args):  # errors in background threads
        import traceback
        sys.stderr.write(f"Error in thread {args.thread.name if args.thread else '?'}:\n"
                         + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    threading.excepthook = _thread_error

    atexit.register(lambda: _write(f"session ended {datetime.now():%Y-%m-%d %H:%M:%S}\n", label="—"))
