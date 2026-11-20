"""AvailabilityScreen: paste a Moxfield deck URL, fetch it, and cross-
reference every card against the collection/other decks (via the root
availability.py module) — showing what's free to use, tied up elsewhere,
or not owned, with colored tiles, a status legend that doubles as a
filter, a price sort, and an Export button (ui.components.export_modal).
"""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QToolButton, QMessageBox,
)

import availability
import moxfield
from app import MTGApp
from models import saved_availability_decks
from models.deck import Deck
from paths import ASSETS_DIR
from ui.components.section_card import back_button
from ui.background import run_in_background
from ui.components.card_section import rebuild_card_sections, quantity_caption
from ui.components.clickable_label import ClickableLabel
from ui.components.sort_button import build_sort_button
from ui.icon_utils import tinted_icon, tinted_pixmap
from ui import theme

ICON_SIZE = QSize(16, 16)


STATUS_COLORS = {
    availability.FREE: QColor(theme.WIN),
    availability.USED: QColor(theme.WARN),
    availability.UNOWNED: QColor(theme.LOSS),
}
STATUS_LABELS = {
    availability.FREE: "Free",
    availability.USED: "Used elsewhere",
    availability.UNOWNED: "Not owned",
}

SORT_PRICE_DESC = "price_desc"
SORT_PRICE_ASC = "price_asc"
SORT_NAME = "name"
SORT_LABELS = {
    SORT_PRICE_DESC: "Price high-low",
    SORT_PRICE_ASC: "Price low-high",
    SORT_NAME: "Name",
}
INACTIVE_COLOR = QColor("#444444")


class _LegendChip(QWidget):
    """A swatch + label that doubles as a status filter toggle — click to
    show/hide that status in the grid below."""

    toggled = Signal(str, bool)  # status, is_active

    def __init__(self, status: str, color: QColor, label_text: str, parent=None):
        """status: one of availability.FREE/USED/UNOWNED, identifying
        which bucket this chip filters. color: swatch color when active.
        label_text: text shown next to the swatch. Starts active."""
        super().__init__(parent)
        self._status = status
        self._color = color
        self._active = True
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._swatch = QLabel()
        self._swatch.setFixedSize(12, 12)
        layout.addWidget(self._swatch)

        self._label = QLabel(label_text)
        layout.addWidget(self._label)

        self._refresh_style()

    def is_active(self) -> bool:
        return self._active

    def mousePressEvent(self, event):
        """Left-click flips the active state, updates the chip's own
        appearance, and emits `toggled` for AvailabilityScreen to
        re-filter the grid."""
        if event.button() == Qt.LeftButton:
            self._active = not self._active
            self._refresh_style()
            self.toggled.emit(self._status, self._active)
        super().mousePressEvent(event)

    def _refresh_style(self):
        """Repaints the swatch/label colors to match the current active
        state (full color when active, dimmed gray when inactive)."""
        color = self._color if self._active else INACTIVE_COLOR
        self._swatch.setStyleSheet(f"background-color: {color.name()}; border-radius: 3px;")
        text_color = theme.TEXT if self._active else theme.DIMMED
        self._label.setStyleSheet(f"color: {text_color};")


def _count_box(count: int, color: QColor) -> QLabel:
    """A small colored badge showing a status count (free/used/unowned),
    for the saved-deck row summary."""
    box = QLabel(str(count))
    box.setAlignment(Qt.AlignCenter)
    box.setFixedWidth(36)
    box.setStyleSheet(
        f"background-color: {color.name()}; color: #1a1a1a; border-radius: 4px;"
        f"font-weight: 600; padding: 3px 0;"
    )
    return box


class _SavedDeckRow(QWidget):
    """A saved deck, rendered as a full-width row (matching the URL bar)
    with its name, free/used/unowned count badges, and missing-cost
    price. Click the row (outside the buttons) to load & re-check that
    deck; Reload re-runs the price/availability check against the
    current collection without re-fetching the deck itself; Delete asks
    for confirmation before forgetting it."""

    load_requested = Signal(str)  # deck_id
    reload_requested = Signal(str)  # deck_id
    remove_requested = Signal(str)  # deck_id

    def __init__(self, entry: dict, parent=None):
        """entry: one saved-decks record — {deck_id, name, url, summary}
        where summary is {"free", "used", "unowned", "missing_cost"}."""
        super().__init__(parent)
        self._deck_id = entry["deck_id"]
        self._name = entry["name"]
        self.setObjectName("savedDeckRow")
        self.setStyleSheet(
            "#savedDeckRow { background-color: #2c2c2c; border-radius: 8px; }"
            "#savedDeckRow:hover { background-color: #363636; }"
        )
        self.setCursor(Qt.PointingHandCursor)

        summary = entry.get("summary") or {}

        # Zero left/right margins: the outer saved_layout already applies
        # the screen's standard 40px margin, so the name text and the
        # Delete button line up exactly with the header/URL bar/Check
        # button above rather than sitting inset from them.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(10)

        name_label = QLabel(entry["name"])
        name_label.setStyleSheet("color: #e8e8e8; font-weight: 500;")
        layout.addWidget(name_label, 1)

        price_label = QLabel(f"Missing cards ≈ €{summary.get('missing_cost', 0):,.2f}")
        price_label.setStyleSheet("color: #bbbbbb;")
        layout.addWidget(price_label)

        layout.addWidget(_count_box(summary.get("free", 0), STATUS_COLORS[availability.FREE]))
        layout.addWidget(_count_box(summary.get("used", 0), STATUS_COLORS[availability.USED]))
        layout.addWidget(_count_box(summary.get("unowned", 0), STATUS_COLORS[availability.UNOWNED]))

        self._reload_btn = QPushButton()
        self._reload_btn.setIcon(tinted_icon(ASSETS_DIR / "reload.png", "#cccccc", size=16))
        self._reload_btn.setIconSize(ICON_SIZE)
        self._reload_btn.setToolTip("Refresh price/availability against your current collection")
        self._reload_btn.setCursor(Qt.PointingHandCursor)
        self._reload_btn.setFixedSize(32, 32)
        self._reload_btn.setStyleSheet(
            "QPushButton { background-color: #4a4a4a; }"
            "QPushButton:hover { background-color: #5a5a5a; }"
            "QPushButton:disabled { background-color: #3a3a3a; }"
        )
        self._reload_btn.clicked.connect(self._on_reload_clicked)
        layout.addWidget(self._reload_btn)

        delete_btn = QPushButton()
        delete_btn.setIcon(tinted_icon(ASSETS_DIR / "trash-bin.png", "#e8a0a0", size=16))
        delete_btn.setIconSize(ICON_SIZE)
        delete_btn.setToolTip("Remove this saved deck")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.setFixedSize(32, 32)
        delete_btn.setStyleSheet(
            "QPushButton { background-color: #4a2323; }"
            "QPushButton:hover { background-color: #6b2f2f; }"
        )
        delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(delete_btn)

    def _on_reload_clicked(self):
        """Slot for the reload button: asks the screen to re-run the
        availability check against the current collection, keeping the
        already-fetched deck contents (no Moxfield re-fetch)."""
        self._reload_btn.setEnabled(False)
        self.reload_requested.emit(self._deck_id)

    def _on_delete_clicked(self):
        """Slot for the Delete button: confirms before forgetting this
        saved deck."""
        answer = QMessageBox.question(
            self,
            "Remove saved deck",
            f"Remove \"{self._name}\" from your saved decks?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.remove_requested.emit(self._deck_id)

    def mousePressEvent(self, event):
        """Clicking anywhere on the row outside its buttons loads that
        deck (buttons consume their own clicks and never reach here)."""
        if event.button() == Qt.LeftButton:
            self.load_requested.emit(self._deck_id)
        super().mousePressEvent(event)


class AvailabilityScreen(QWidget):
    """Paste a Moxfield deck URL and see which of its cards are free to
    use, already tied up in another active deck, or not owned at all."""

    card_clicked = Signal(dict)
    export_requested = Signal(list)
    back_requested = Signal()  # Back on the blank check screen (to the Other Apps page)

    def __init__(self, app: MTGApp):
        """Builds the (initially empty) screen chrome — URL input, Check/
        Sort/Export buttons, the status summary + legend-filter row, and
        the scrollable section container. Nothing is fetched until the
        user clicks Check."""
        super().__init__()
        self.app = app
        self._bg_tasks = []  # keeps background tasks alive — see ui/background.py

        # Cached from the last successful check, so toggling a legend chip
        # or the sort order re-renders instantly instead of re-fetching.
        self._last_deck_name = None
        self._last_commander_names = set()
        self._last_results = None
        self._last_deck_id = None
        self._last_url = ""
        self._active_statuses = {availability.FREE, availability.USED, availability.UNOWNED}
        self._sort_mode = SORT_NAME

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(40, 30, 40, 10)
        title_layout.setSpacing(2)

        # Back (an app on the Other Apps page, like the others): while a
        # deck's results are showing it clears back to the blank check
        # screen (and the saved-decks list); from there, to Other Apps.
        self._viewing = False
        back_btn = back_button(self._on_back_clicked)
        title_layout.addWidget(back_btn, 0, Qt.AlignLeft)
        title_layout.addSpacing(10)

        # Title row: the title, and — while viewing a deck's results — the
        # Save bookmark and Export at the top right, like other screens'
        # header buttons
        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header = QLabel("Availability Checker")
        header.setObjectName("screenTitle")
        header_row.addWidget(header)
        header_row.addStretch()
        title_layout.addLayout(header_row)

        outer.addWidget(title_area)

        # Row 1: URL input, Check, Sort
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(40, 0, 40, 16)
        input_layout.setSpacing(12)

        self._url_input = QLineEdit()
        self._url_input.setObjectName("searchInput")
        self._url_input.setPlaceholderText("Paste a Moxfield deck URL…")
        self._url_input.returnPressed.connect(self._on_check_clicked)
        input_layout.addWidget(self._url_input, 1)

        self._check_btn = QPushButton("Check")
        self._check_btn.clicked.connect(self._on_check_clicked)
        input_layout.addWidget(self._check_btn)

        # Only appears while viewing a deck's results — a bare bookmark
        # icon (title row, top right). Swaps to the filled "checked" icon
        # once the current deck is saved.
        self._save_btn = ClickableLabel()  # a bare bookmark icon, not a bordered button
        self._save_btn.setPixmap(tinted_pixmap(ASSETS_DIR / "bookmark-unchecked.png", theme.ACCENT, size=20))
        self._save_btn.setToolTip("Save this deck to the list below the URL box")
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._save_btn.hide()
        header_row.addWidget(self._save_btn, 0, Qt.AlignVCenter)

        # Only appears once there are results to export — see _on_check_finished
        self._export_btn = QPushButton("Export")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._export_btn.hide()
        header_row.addWidget(self._export_btn, 0, Qt.AlignVCenter)

        outer.addWidget(input_row)

        # Saved-deck rows, full-width to match the URL bar — only shown on
        # the blank check screen (i.e. no deck currently being displayed).
        # Each row summarizes that deck's last check: free/used/unowned
        # counts and missing-cards cost.
        self._saved_row = QWidget()
        self._saved_layout = QVBoxLayout(self._saved_row)
        self._saved_layout.setContentsMargins(40, 0, 40, 16)
        self._saved_layout.setSpacing(8)
        outer.addWidget(self._saved_row)
        self._refresh_saved_row()

        # Row 2: status/summary text (left) + legend chips, which double as
        # status filters (right)
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(40, 0, 40, 16)
        status_layout.setSpacing(12)

        self._status_label = QLabel()
        self._status_label.setObjectName("resultCount")
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label, 1)

        self._legend_chips = {}
        for status in (availability.FREE, availability.USED, availability.UNOWNED):
            chip = _LegendChip(status, STATUS_COLORS[status], STATUS_LABELS[status])
            chip.toggled.connect(self._on_legend_toggled)
            status_layout.addWidget(chip)
            self._legend_chips[status] = chip

        self._sort_btn = self._build_sort_button()
        self._sort_btn.hide()
        status_layout.addWidget(self._sort_btn)

        outer.addWidget(status_row)

        # Scrollable, sectioned card grid (grouped by type, like deck detail)
        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._sections_container = QWidget()
        self._sections_layout = QVBoxLayout(self._sections_container)
        self._sections_layout.setContentsMargins(40, 0, 40, 40)
        self._sections_layout.setSpacing(24)
        self._sections_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self._sections_container)
        outer.addWidget(scroll, 1)

    def _build_sort_button(self) -> QToolButton:
        """Builds the "Sort" dropdown button (price-high-low/price-low-
        high/name — see ui.components.sort_button). Returns the button."""
        return build_sort_button(SORT_LABELS, self._sort_mode, self._on_sort_changed)

    def _on_sort_changed(self, mode: str):
        """Slot for the Sort menu: records the new mode and re-renders
        (from cached results, no re-fetch) if there's anything to show.
        mode: one of SORT_PRICE_DESC/SORT_PRICE_ASC/SORT_NAME."""
        self._sort_mode = mode
        if self._last_results is not None:
            self._apply_filter()

    def _on_legend_toggled(self, status: str, is_active: bool):
        """Slot for a _LegendChip's `toggled` signal: updates which
        statuses are shown and re-renders (from cached results, no
        re-fetch). status: availability.FREE/USED/UNOWNED. is_active:
        the chip's new state."""
        if is_active:
            self._active_statuses.add(status)
        else:
            self._active_statuses.discard(status)
        if self._last_results is not None:
            self._apply_filter()

    def _on_check_clicked(self):
        """Slot for the Check button (and Enter in the URL box): parses
        the URL, validates login state, then runs the fetch+check in the
        background."""
        url = self._url_input.text().strip()
        deck_id = moxfield.extract_deck_id(url)
        if not deck_id:
            self._status_label.setText("That doesn't look like a Moxfield deck URL.")
            return
        if not self.app.is_logged_in:
            self._status_label.setText("Log in first via the sidebar avatar.")
            return

        self._last_url = url
        self._last_deck_id = deck_id
        self._check_btn.setEnabled(False)
        self._status_label.setText("Checking…")
        run_in_background(
            lambda: self._fetch_and_check(deck_id),
            self._bg_tasks,
            on_finished=self._on_check_finished,
            on_failed=self._on_check_failed,
        )

    def _fetch_and_check(self, deck_id: str):
        """Background-task body: force-fetches the deck at `deck_id` and
        runs check_availability against the current collection/decks.
        Returns (deck_name, commander_names, results) for
        _on_check_finished."""
        deck = Deck(deck_id, "")
        deck.load(force=True)
        results = availability.check_availability(self.app, deck.cards)
        commander_names = {c["name"] for c in deck.commanders}
        return deck.name, commander_names, results

    def _on_check_finished(self, result):
        """Background-task callback for a successful check: caches the
        result, reveals the Export button, and renders it. result: the
        (deck_name, commander_names, results) tuple from
        _fetch_and_check."""
        self._check_btn.setEnabled(True)
        self._last_deck_name, self._last_commander_names, self._last_results = result
        self._set_viewing_deck(True)
        self._apply_filter()
        self._refresh_saved_row()

    def _on_back_clicked(self):
        if self._viewing:
            self._on_new_check_clicked()
        else:
            self.back_requested.emit()

    def _set_viewing_deck(self, is_viewing: bool):
        """Toggles the row between the two states: blank check screen
        (URL box + Check button, saved-deck rows below) and viewing a
        checked deck's results (Back button + Sort/Export/Save, no URL
        box). The Save bookmark stays visible either way, swapping
        between its unchecked/checked icon — see _refresh_save_icon."""
        self._viewing = is_viewing
        self._url_input.setVisible(not is_viewing)
        self._check_btn.setVisible(not is_viewing)
        self._sort_btn.setVisible(is_viewing)
        self._export_btn.setVisible(is_viewing)
        self._save_btn.setVisible(is_viewing)
        self._refresh_save_icon()

    def _refresh_save_icon(self):
        """Swaps the Save bookmark between its unchecked (not yet saved)
        and checked (already saved) icon for the currently-viewed deck."""
        already_saved = self._last_deck_id is not None and saved_availability_decks.is_saved(self._last_deck_id)
        icon_name = "bookmark-checked.png" if already_saved else "bookmark-unchecked.png"
        self._save_btn.setPixmap(tinted_pixmap(ASSETS_DIR / icon_name, theme.ACCENT, size=20))
        self._save_btn.setToolTip("Saved — click to remove" if already_saved else "Save this deck")

    def _on_check_failed(self, message: str):
        """Background-task callback for a failed check: surfaces the
        error in the status line. message: str(exception) from the
        failed fetch."""
        self._check_btn.setEnabled(True)
        self._status_label.setText(f"Couldn't load that deck: {message}")

    def _on_export_clicked(self):
        """Slot for the Export button: emits export_requested with the
        last check's full (unfiltered) results, for ExportModal to
        display. No-ops if nothing's been checked yet."""
        if self._last_results is not None:
            self.export_requested.emit(self._last_results)

    def _on_save_clicked(self):
        """Slot for the Save bookmark: toggles the currently-viewed deck's
        saved state. If it's not saved yet, stores its URL and result
        summary so it shows up as a row on the blank check screen; if
        it's already saved, clicking again forgets it. No-ops if nothing's
        been checked."""
        if self._last_deck_id is None or self._last_results is None:
            return
        if saved_availability_decks.is_saved(self._last_deck_id):
            saved_availability_decks.remove_deck(self._last_deck_id)
        else:
            saved_availability_decks.save_deck(
                self._last_deck_id,
                self._last_deck_name or self._last_deck_id,
                self._last_url,
                self._summary_stats(self._last_results),
            )
        self._refresh_save_icon()
        self._refresh_saved_row()

    @staticmethod
    def _summary_stats(results: list[dict]) -> dict:
        """Rolls up a full (unfiltered) results list into the counts/cost
        shown on the status line and on a saved-deck row."""
        return {
            "free": sum(1 for r in results if r["status"] == availability.FREE),
            "used": sum(1 for r in results if r["status"] == availability.USED),
            "unowned": sum(1 for r in results if r["status"] == availability.UNOWNED),
            "missing_cost": sum(r["missing_cost"] for r in results),
        }

    def _refresh_saved_row(self):
        """Rebuilds the saved-deck rows from disk. Only visible on the
        blank check screen (no deck currently displayed) and when there's
        at least one saved deck."""
        while self._saved_layout.count():
            item = self._saved_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        saved = saved_availability_decks.get_saved()
        for entry in saved:
            row = _SavedDeckRow(entry)
            row.load_requested.connect(self._on_saved_row_load)
            row.reload_requested.connect(self._on_saved_row_reload)
            row.remove_requested.connect(self._on_saved_row_remove)
            self._saved_layout.addWidget(row)

        self._saved_row.setVisible(bool(saved) and self._last_results is None)

    def _on_saved_row_load(self, deck_id: str):
        """Slot for a saved row's click: puts its URL back in the input
        box and re-runs the check."""
        for entry in saved_availability_decks.get_saved():
            if entry["deck_id"] == deck_id:
                self._url_input.setText(entry["url"])
                break
        self._on_check_clicked()

    def _on_saved_row_remove(self, deck_id: str):
        """Slot for a saved row's Delete button (after confirmation):
        forgets that deck and refreshes the row list."""
        saved_availability_decks.remove_deck(deck_id)
        self._refresh_saved_row()

    def _on_saved_row_reload(self, deck_id: str):
        """Slot for a saved row's reload button: re-runs the
        price/availability check against the current collection, reusing
        the deck's already-cached card list (no Moxfield re-fetch) —
        just picks up changes made to the collection since it was saved."""
        entry = next((e for e in saved_availability_decks.get_saved() if e["deck_id"] == deck_id), None)
        if entry is None:
            return
        run_in_background(
            lambda: self._recheck_saved_deck(deck_id, entry["name"], entry["url"]),
            self._bg_tasks,
            on_finished=self._on_saved_reload_finished,
            on_failed=self._on_saved_reload_failed,
        )

    def _recheck_saved_deck(self, deck_id: str, name: str, url: str):
        """Background-task body: loads the deck from its local cache
        (force=False) and re-runs check_availability against the current
        collection. If the deck's cache was cleared since it was saved,
        load(force=False) silently leaves it empty (no cards, no error) —
        so fall back to a real fetch in that case rather than reporting
        zero cards everywhere. Returns (deck_id, name, url, summary) for
        _on_saved_reload_finished."""
        deck = Deck(deck_id, "")
        deck.load()
        if not deck.cards:
            deck.load(force=True)
        results = availability.check_availability(self.app, deck.cards)
        return deck_id, deck.name or name, url, self._summary_stats(results)

    def _on_saved_reload_finished(self, result):
        """Background-task callback for a successful reload: persists the
        refreshed summary and re-renders the saved rows."""
        deck_id, name, url, summary = result
        saved_availability_decks.save_deck(deck_id, name, url, summary)
        self._refresh_saved_row()

    def _on_saved_reload_failed(self, message: str):
        """Background-task callback for a failed reload: surfaces the
        error in the status line and re-enables the row's reload button
        (via a full refresh)."""
        self._status_label.setText(f"Couldn't refresh that deck: {message}")
        self._refresh_saved_row()

    def _on_new_check_clicked(self):
        """Slot for the Back button: clears the currently-displayed deck
        and returns to the blank check screen (URL box + saved-deck
        rows)."""
        self._last_results = None
        self._last_deck_name = None
        self._last_commander_names = set()
        self._last_deck_id = None
        self._last_url = ""
        self._url_input.clear()
        self._status_label.clear()
        self._set_viewing_deck(False)
        rebuild_card_sections(
            self._sections_layout, [], set(),
            caption_fn=self._caption_with_cost,
            on_click=self.card_clicked.emit,
            color_fn=lambda card: STATUS_COLORS[card["status"]],
            sort_fn=self._sorted_cards,
        )
        self._refresh_saved_row()

    def _apply_filter(self):
        """Narrows self._last_results to the currently-active legend
        statuses and re-renders. Called after a check completes or
        whenever a legend chip / sort mode changes."""
        filtered = [r for r in self._last_results if r["status"] in self._active_statuses]
        self._render_results(self._last_deck_name, self._last_commander_names, filtered)

    def _render_results(self, deck_name: str, commander_names: set, results: list[dict]):
        """Updates the summary line and rebuilds the type-grouped card
        grid from `results` (already filtered by _apply_filter to the
        active legend statuses). deck_name/commander_names come from the
        last check; the summary counts always use self._last_results
        (unfiltered) — see the comment below."""
        # Counts/cost always reflect the full check, not just what's shown
        # after filtering — "how much would it cost to finish this deck"
        # shouldn't change just because you hid the free cards.
        stats = self._summary_stats(self._last_results or [])
        self._status_label.setText(
            f"{deck_name} — {stats['free']} free · {stats['used']} used elsewhere · "
            f"{stats['unowned']} not owned  ·  missing cards cost ≈ €{stats['missing_cost']:,.2f}"
        )

        rebuild_card_sections(
            self._sections_layout,
            results,
            commander_names,
            caption_fn=self._caption_with_cost,
            on_click=self.card_clicked.emit,
            color_fn=lambda card: STATUS_COLORS[card["status"]],
            sort_fn=self._sorted_cards,
        )

    @staticmethod
    def _caption_with_cost(card: dict) -> str:
        """Tile caption: quantity_caption() plus a "(€X.XX)" suffix when
        this card has a nonzero missing_cost (i.e. some/all copies still
        need buying)."""
        caption = quantity_caption(card)
        if card["missing_cost"] > 0:
            caption += f" (€{card['missing_cost']:,.2f})"
        return caption

    def _sorted_cards(self, cards: list[dict]) -> list[dict]:
        """Orders one section's cards per the current Sort menu choice:
        by missing_cost (high-low or low-high) or alphabetically by name."""
        if self._sort_mode == SORT_PRICE_DESC:
            return sorted(cards, key=lambda c: c["missing_cost"], reverse=True)
        if self._sort_mode == SORT_PRICE_ASC:
            return sorted(cards, key=lambda c: c["missing_cost"])
        return sorted(cards, key=lambda c: c["name"].lower())
