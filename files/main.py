"""Entry point for the GUI app. Sets up crash logging, builds the
QApplication and MainWindow, and wires up a clean-shutdown handler so
background image/deck-load threads don't get torn down mid-flight. Run
this file directly to launch the app (add --self-test to check a build
instead — see self_test.py).
"""

import faulthandler
import sys
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import paths
import session
from app import MTGApp
from ui.main_window import MainWindow

# your folder (files/ from source, %APPDATA% for the .exe) — see paths.py
paths.USER_ROOT.mkdir(parents=True, exist_ok=True)
_crash_log = open(paths.CRASH_LOG_PATH, "w")
faulthandler.enable(file=_crash_log)


def load_stylesheet(path: Path) -> str:
    """Reads a .qss stylesheet file as text. path: path to the .qss file.
    Returns its contents, ready to pass to QApplication.setStyleSheet()."""
    return path.read_text(encoding="utf-8")


def main():
    """Builds and runs the application: loads the last-logged-in user (if
    any) from session.py, creates the QApplication/MainWindow, and blocks
    until the window closes."""
    mtg_app = MTGApp(session.get_saved_username())
    # No eager deck.load() — each deck loads on demand when its detail screen opens

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(paths.APP_NAME)
    qt_app.setWindowIcon(QIcon(str(paths.APP_ICON_PATH)))
    qt_app.setStyleSheet(load_stylesheet(paths.STYLE_PATH))

    window = MainWindow(mtg_app)
    window.showMaximized()

    def _shutdown():
        # Background image/deck-load tasks (ui/image_loader.py, ui/background.py)
        # hold Qt signal objects that must not be destroyed while a worker
        # thread is still using them. Drop anything not yet started and let
        # the few still-running tasks finish before Qt tears down.
        pool = QThreadPool.globalInstance()
        pool.clear()
        pool.waitForDone()

    qt_app.aboutToQuit.connect(_shutdown)
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    if "--self-test" in sys.argv:  # check a build without opening a window — see self_test.py
        import self_test
        sys.exit(self_test.run())
    main()
