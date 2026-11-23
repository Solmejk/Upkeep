"""UpdateFlow: checking for and installing updates from the UI (the
GitHub side is updater.py). MainWindow owns one; the sidebar's "Update
available" button and Settings → Updates both drive it.

    check(manual)  asks GitHub in the background; a newer release emits
                   `available` (the sidebar button appears). A manual check
                   (Settings) also says "up to date" / shows errors.
    offer()        "Upkeep X is available — update now?", then downloads
                   the Setup, starts it and quits; the Setup reopens the new
                   version. Portable copies / source runs get the download
                   page instead.
"""

import sys

from PySide6.QtCore import QObject, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

import updater
from ui.background import run_in_background
from version import VERSION

NOTES_PREVIEW = 600  # characters of release notes shown in the update prompt


def version_label(version: str = VERSION) -> str:
    return f"v{version}" if updater.parse_version(version) else "a development build"


class UpdateFlow(QObject):
    available = Signal(object)    # updater.Release, newer than this version
    status_changed = Signal(str)  # one line for Settings → Updates
    _progress = Signal(int, int)  # download progress, from the worker thread

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._bg_tasks = []  # see ui/background.py
        self._checking = False
        self._manual = False
        self.release = None   # the newer release, once found
        self._dialog = None
        self._progress.connect(self._on_progress)

    # ------------------------------------------------------------ check
    def check(self, manual: bool = False):
        if self._checking:
            return
        self._checking, self._manual = True, manual
        self.status_changed.emit("Checking for updates…")
        run_in_background(updater.check, self._bg_tasks, self._on_checked, self._on_check_failed)

    def _on_checked(self, release):
        self._checking = False
        if release is not None and updater.is_newer(release):
            self.release = release
            self.status_changed.emit(f"Upkeep v{release.version} is available.")
            self.available.emit(release)
            if self._manual:
                self.offer()
            return
        self.status_changed.emit("No releases published yet." if release is None
                                 else f"You're up to date (latest release: v{release.version}).")
        if self._manual:
            QMessageBox.information(self._window, "Updates", "Upkeep is up to date.")

    def _on_check_failed(self, message: str):
        self._checking = False
        self.status_changed.emit("Couldn't check for updates — are you online?")
        if self._manual:
            QMessageBox.warning(self._window, "Updates", f"Couldn't check for updates:\n{message}")

    # ---------------------------------------------------------- install
    def offer(self):
        """Asks to update to the found release, then does it."""
        release = self.release
        if release is None:
            return
        notes = release.notes.strip()
        if len(notes) > NOTES_PREVIEW:
            notes = notes[:NOTES_PREVIEW].rstrip() + "…"
        box = QMessageBox(self._window)
        box.setWindowTitle("Update available")
        box.setText(f"Upkeep v{release.version} is available — you have {version_label()}.")
        if notes:
            box.setInformativeText(notes)

        if updater.can_self_update() and release.setup_url:
            box.setInformativeText((notes + "\n\n" if notes else "")
                                   + "Upkeep will close, update and reopen. Your data is kept.")
            update_btn = box.addButton("Update now", QMessageBox.AcceptRole)
            box.addButton("Later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is update_btn:
                self._download(release)
        else:  # portable copy / from source: nothing to update in place
            page_btn = box.addButton("Open download page", QMessageBox.AcceptRole)
            box.addButton("Later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is page_btn:
                QDesktopServices.openUrl(QUrl(release.page_url))

    def _download(self, release):
        self._dialog = QProgressDialog(f"Downloading Upkeep v{release.version}…", None, 0, 100, self._window)
        self._dialog.setWindowTitle("Updating Upkeep")
        self._dialog.setWindowModality(Qt.ApplicationModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.setAutoClose(False)
        self._dialog.setValue(0)
        self._dialog.show()
        run_in_background(
            lambda: updater.download(release, self._progress.emit),
            self._bg_tasks, self._on_downloaded, self._on_download_failed)

    def _on_progress(self, done: int, total: int):
        if self._dialog is None:
            return
        if total:
            self._dialog.setValue(int(done * 100 / total))
            self._dialog.setLabelText(f"Downloading Upkeep… {done / 1e6:.0f} of {total / 1e6:.0f} MB")
        else:
            self._dialog.setRange(0, 0)  # unknown size: busy indicator

    def _on_downloaded(self, setup_path):
        self._dialog.setLabelText("Starting the installer…")
        try:
            updater.run_installer(setup_path, self.release.version)
        except OSError as e:
            self._on_download_failed(f"couldn't start the installer: {e}")
            return
        print(f"update: started the installer for v{self.release.version}; closing")
        QApplication.quit()  # the Setup replaces the program and reopens it

    def report_last_update(self):
        """Called once at startup: if an update was started last time, say
        whether it arrived — in the log, and with a message if it didn't
        (a silent Setup that fails says nothing itself)."""
        result = updater.pending_result()
        if result is None:
            return
        outcome, old, new = result
        if outcome == "updated":
            print(f"update: now running v{new} (was {old})")
            self.status_changed.emit(f"Updated to v{new}.")
            return
        print(f"update: v{new} didn't install, still on {VERSION} — see {updater.INSTALL_LOG_PATH}", file=sys.stderr)
        self.status_changed.emit(f"The update to v{new} didn't install.")
        QMessageBox.warning(
            self._window, "Update didn't install",
            f"Upkeep v{new} was downloaded, but the installer couldn't replace the program — "
            f"you're still on {version_label()}.\n\nTry again from Settings → Updates. If it keeps "
            f"failing, close every Upkeep window (check Task Manager), or run the Setup from the "
            f"Releases page by hand.\n\nThe installer's log: {updater.INSTALL_LOG_PATH}")

    def _on_download_failed(self, message: str):
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
        QMessageBox.warning(self._window, "Update failed",
                            f"The update couldn't be downloaded:\n{message}\n\nYou can try again from Settings → Updates.")
