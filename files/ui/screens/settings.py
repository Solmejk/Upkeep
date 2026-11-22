"""SettingsScreen: the cache-clearing controls (per-category toggles +
a Clear button, emitting clear_cache_requested for MainWindow to act
on), a Sync log sub-page showing when Moxfield was last synced
(read from sync_log.py's text file), a Search syntax sub-page (the
guide in ui/search_help.py), and an Updates card (ui/update_flow.py).
"""

from PySide6.QtCore import Signal

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QStackedWidget, QPlainTextEdit, QTextBrowser, QScrollArea,
)

import sync_log
from ui.components.section_card import SectionCard, back_button
from ui.components.artist_proofs_panel import ArtistProofsPanel
from ui.search_help import SEARCH_HELP_HTML
from ui.components.toggle_switch import ToggleSwitch
from ui.update_flow import version_label

SYNC_KINDS = ("Collection", "Prices", "Decks", "Profile")


class SettingsScreen(QWidget):
    """User settings: cache controls, plus the Sync log and Search
    syntax sub-pages."""

    clear_cache_requested = Signal(list)  # list of strings: "collection", "decks", "profile", "images"
    proofs_changed = Signal()  # artist proofs added / changed / removed
    refresh_requested = Signal()  # "Refresh all" (Sync section): profile, collection, prices, decks
    check_updates_requested = Signal()  # Updates → Check for updates
    install_update_requested = Signal()  # Updates → Update to vX (shown once one is found)

    def __init__(self, app=None):
        """Builds the main settings page and its sub-pages (Sync log,
        Search syntax) as pages of a stack, main page shown first."""
        super().__init__()
        self.app = app
        self._refreshing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        layout.addWidget(self._pages)

        self._main_page = self._build_main_page()
        self._log_page = self._build_log_page()
        self._search_help_page = self._build_search_help_page()
        self._proofs_page = self._build_proofs_page()
        self._pages.addWidget(self._main_page)
        self._pages.addWidget(self._log_page)
        self._pages.addWidget(self._search_help_page)
        self._pages.addWidget(self._proofs_page)

    def _build_main_page(self) -> QWidget:
        """The top-level settings page: title + sections."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(20)

        # Header
        title = QLabel("Settings")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        for section in (self._build_sync_log_section(), self._build_cache_section(),
                        self._build_search_help_section(), self._build_proofs_section(),
                        self._build_updates_section()):
            outer.addWidget(section)  # SectionCards: fixed height, the page scrolls

        outer.addStretch()

        # Scrollable — the sections don't all fit in a short window
        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")  # transparent, borderless
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _build_sync_log_section(self) -> QWidget:
        """The "Sync" card on the main page: Refresh all (everything from
        Moxfield, prices from Scryfall) and a button to the log sub-page."""
        section = SectionCard(
            "Sync",
            "Refresh all fetches your profile, collection and decks from Moxfield, and your "
            "collection's prices from Scryfall. The log shows when each was last synced.")
        section.add_button("View log", self._show_log_page, secondary=True)
        self._refresh_all_btn = section.add_button("Refresh all", self.refresh_requested.emit)
        self._update_refresh_button()
        return section

    def set_refresh_enabled(self, enabled: bool):
        """Toggles Refresh all between normal and "Refreshing…" (disabled)
        — called by MainWindow around the background Moxfield fetch."""
        self._refreshing = not enabled
        self._update_refresh_button()

    def _update_refresh_button(self):
        """Disabled while logged out or refreshing. (This screen isn't
        rebuilt on login / logout, so it's re-checked whenever it's shown.)"""
        self._refresh_all_btn.setEnabled(bool(self.app and self.app.is_logged_in) and not self._refreshing)
        self._refresh_all_btn.setText("Refreshing…" if self._refreshing else "Refresh all")

    def showEvent(self, event):
        super().showEvent(event)
        self._update_refresh_button()

    def _build_updates_section(self) -> QWidget:
        """The "Updates" card: this version, the last check's result, and
        Check for updates / Update now (MainWindow's UpdateFlow does the
        work, via the two signals)."""
        section = SectionCard(
            "Updates",
            f"You're running Upkeep {version_label()}. New versions come from the GitHub "
            "releases page; Upkeep checks for one every time it starts.")
        self._update_status = QLabel("Not checked yet.")
        self._update_status.setObjectName("settingsLabel")
        self._update_status.setWordWrap(True)
        section.body.addWidget(self._update_status)
        section.add_button("Check for updates", self.check_updates_requested.emit, secondary=True)
        self._install_update_btn = section.add_button("Update now", self.install_update_requested.emit)
        self._install_update_btn.hide()
        return section

    def set_update_status(self, text: str):
        self._update_status.setText(text)

    def show_update_available(self, release):
        self._install_update_btn.setText(f"Update to v{release.version}")
        self._install_update_btn.show()

    def _build_proofs_section(self) -> QWidget:
        """The "Artist proofs" card on the main page: what they are and a
        button to the management page."""
        section = SectionCard(
            "Custom card images",
            "Artist proofs, signed or altered cards — your own front and / or back image for a "
            "printing, shown instead of the normal image everywhere and flippable in showcases.")
        section.add_button("Edit cards", lambda: self._pages.setCurrentWidget(self._proofs_page))
        return section

    def _build_proofs_page(self) -> QWidget:
        """The Artist proofs sub-page: back button + ArtistProofsPanel."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(16)

        top_bar = QHBoxLayout()
        back_btn = back_button(lambda: self._pages.setCurrentWidget(self._main_page))
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        outer.addLayout(top_bar)

        title = QLabel("Custom card images")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        self.proofs_panel = ArtistProofsPanel(self.app)
        self.proofs_panel.proofs_changed.connect(self.proofs_changed.emit)
        outer.addWidget(self.proofs_panel, 1)
        return page

    def _build_search_help_section(self) -> QWidget:
        """The "Search syntax" card on the main page: a one-line summary
        and a button that opens the full guide."""
        section = SectionCard(
            "Search syntax",
            "The Collection, deck and Deck Maker card searches use Scryfall's syntax, "
            "e.g. t:creature c:g mv<=3. See every filter with examples.")
        section.add_button("Open guide", lambda: self._pages.setCurrentWidget(self._search_help_page))
        return section

    def _build_search_help_page(self) -> QWidget:
        """The Search syntax sub-page: back button + the guide."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(16)

        top_bar = QHBoxLayout()
        back_btn = back_button(lambda: self._pages.setCurrentWidget(self._main_page))
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        outer.addLayout(top_bar)

        title = QLabel("Search syntax")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        guide = QTextBrowser()
        guide.setObjectName("searchHelp")
        guide.setOpenExternalLinks(True)
        guide.setHtml(SEARCH_HELP_HTML)
        outer.addWidget(guide, 1)

        return page

    def _build_log_page(self) -> QWidget:
        """The Sync log sub-page: back button, last-synced summary, and
        the full log (newest first). Filled in by _show_log_page each
        time it's opened, so it's never stale."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(16)

        top_bar = QHBoxLayout()
        back_btn = back_button(lambda: self._pages.setCurrentWidget(self._main_page))
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        outer.addLayout(top_bar)

        title = QLabel("Sync log")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        self._last_synced_label = QLabel()
        self._last_synced_label.setObjectName("settingsLabel")
        outer.addWidget(self._last_synced_label)

        self._log_text = QPlainTextEdit()
        self._log_text.setObjectName("syncLogText")
        self._log_text.setReadOnly(True)
        self._log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        outer.addWidget(self._log_text, 1)

        return page

    def _show_log_page(self):
        """Reloads the log from disk and switches to the log sub-page."""
        rows = []
        for kind in SYNC_KINDS:
            when = sync_log.last_success(kind) or "never"
            rows.append(f"<b>{kind}:</b> {when}")
        self._last_synced_label.setText("Last synced — " + " · ".join(rows))

        lines = sync_log.read_lines()
        self._log_text.setPlainText(
            "\n".join(reversed(lines)) if lines else "No syncs recorded yet."
        )
        self._pages.setCurrentWidget(self._log_page)

    def _build_cache_section(self) -> QWidget:
        """Builds the "Cache" card: a toggle per category plus a "Clear
        selected" button. Returns the assembled section widget."""
        section = SectionCard(
            "Cache", "Choose what to clear. Cleared data will be re-fetched on next app launch.")
        self._collection_toggle = self._toggle_row(section.body, "Collection")
        self._decks_toggle = self._toggle_row(section.body, "Decks")
        self._profile_toggle = self._toggle_row(section.body, "Profile")
        self._images_toggle = self._toggle_row(section.body, "Images")
        section.add_button("Clear selected", self._on_clear_clicked)
        return section

    def _toggle_row(self, parent_layout: QVBoxLayout, label: str) -> ToggleSwitch:
        """Adds one "label ... toggle" row to `parent_layout` (checked by
        default) and returns the toggle so the caller can read its state
        later."""
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setObjectName("settingsLabel")
        row_layout.addWidget(lbl)
        row_layout.addStretch()

        toggle = ToggleSwitch(checked=True)
        row_layout.addWidget(toggle)

        parent_layout.addLayout(row_layout)  # ← addLayout, not addWidget
        return toggle

    def _on_clear_clicked(self):
        """Slot for "Clear selected": collects the checked categories and
        emits clear_cache_requested with them (no-op if none are checked)."""
        targets = []
        if self._collection_toggle.isChecked():
            targets.append("collection")
        if self._decks_toggle.isChecked():
            targets.append("decks")
        if self._profile_toggle.isChecked():
            targets.append("profile")
        if self._images_toggle.isChecked():
            targets.append("images")
        if targets:
            self.clear_cache_requested.emit(targets)
