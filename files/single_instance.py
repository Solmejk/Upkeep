"""Only one Upkeep at a time (per Windows user).

Moxfield allows Upkeep 1 request per second; moxfield.py's limiter only
paces the requests of its own process, so two Upkeeps open at once could
go over it together. So a second start doesn't open another window: it
asks the running Upkeep to come to the front, and quits.

    acquire()          take the lock (a QLockFile in the user's temp
                       folder — shared by the installed app and running
                       from source); None if another Upkeep has it. A lock
                       left by a crashed / killed Upkeep is taken over.
    notify_running()   in the second start: ask the running Upkeep to show
                       its window (True if it answered).
    ShowRequests       in the running Upkeep: calls on_show for each such
                       request.
"""

import getpass
import re
import sys

from PySide6.QtCore import QDir, QLockFile, QObject, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

import paths

_USER = re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser() or "user")
_NAME = re.sub(r"[^A-Za-z0-9_-]", "_", paths.APP_NAME)
LOCK_PATH = f"{QDir.tempPath()}/{_NAME}-{_USER}.lock"
SERVER_NAME = f"{_NAME}-{_USER}-instance"
_SHOW = b"show"

_lock = None  # the held QLockFile — kept for the whole run


def acquire(lock_path: str = LOCK_PATH):
    """Takes the single-instance lock; returns it, or None if another
    running Upkeep holds it. The lock is released when this process ends,
    however it ends."""
    global _lock
    lock = QLockFile(lock_path)
    lock.setStaleLockTime(0)  # never "stale" by age — only if its process is gone
    if not lock.tryLock(0):
        return None
    _lock = lock
    return lock


def notify_running(server_name: str = SERVER_NAME, timeout_ms: int = 1000) -> bool:
    """Asks the running Upkeep to bring its window forward. True if it
    got the message."""
    if sys.platform == "win32":
        try:  # this (just started) process may hand over the foreground
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except (AttributeError, OSError):
            pass
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(_SHOW)
    socket.flush()  # usually sends it all at once: then there's nothing left to wait for
    ok = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return ok


class ShowRequests(QObject):
    """Listens for notify_running() from later starts; calls on_show()."""

    def __init__(self, on_show, server_name: str = SERVER_NAME, parent=None):
        super().__init__(parent)
        self._on_show = on_show
        self._server = QLocalServer(self)
        # we hold the lock, so a server left under this name is a dead one
        QLocalServer.removeServer(server_name)
        if not self._server.listen(server_name):
            print(f"single instance: can't listen ({self._server.errorString()})", file=sys.stderr)
        self._server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._on_ready(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._on_ready(socket)

    def _on_ready(self, socket):
        if _SHOW in bytes(socket.readAll()):
            self._on_show()


def bring_to_front(window):
    """Shows `window` restored (if minimized) and in front."""
    window.setWindowState(window.windowState() & ~Qt.WindowMinimized)
    if window.isHidden():
        window.showMaximized()
    window.raise_()
    window.activateWindow()
