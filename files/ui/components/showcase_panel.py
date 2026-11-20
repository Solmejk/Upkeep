"""ShowcasePanel: the Home screen's showcases — a dropdown to pick which
showcase is shown, and its cards as images in the user's order. Locked
by default: clicking a card just shows its info. Clicking the showcase's
name unlocks editing — Add cards, Rename, Delete, drag to reorder,
right-click to remove — until Save locks it again. Changes are written
as they're made (models.showcases); Save is what locks.
"""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QListView, QAbstractItemView, QMenu,
    QInputDialog, QMessageBox, QCheckBox, QStyle, QStyledItemDelegate,
)

QWIDGETSIZE_MAX = 16777215  # Qt's "no maximum" widget size

# The showcase last picked this session — the Home screen (and this panel)
# is rebuilt on refreshes, which shouldn't jump back to the default.
NEW_SHOWCASE_ITEM = "+ New showcase…"
_session_showcase_id = None

import availability
import scryfall
from card_fields import plural
from card_search import DFC_LAYOUTS
from models import artist_proofs, showcases
from ui.components.image_tile import make_placeholder
from ui.components.showcase_picker import ShowcasePickerDialog
from ui.image_loader import ImageLoader

CARD_WIDTH = 200
CARD_HEIGHT = 279
CARD_RADIUS = 12
CARD_GAP = 8  # around each card, unless the showcase is set to "No gaps"
# "No gaps": just the card's own printed corner — enough to hide the white
# corner fill in Scryfall's card images where four cards meet
GAPLESS_RADIUS = 9
MAX_PER_ROW = 12
REF_ROLE = Qt.UserRole  # list items: the card ref


class _ShowcaseList(QListWidget):
    """The card list; emits order_changed after a drag-and-drop reorder
    (however Qt carried out the move internally)."""

    order_changed = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.order_changed.emit()


class _CardDelegate(QStyledItemDelegate):
    """Draws just the card image, centred in its cell — no margins (so
    "No gaps" cards really touch), and no hover / selection / focus look."""

    def paint(self, painter, option, index):
        icon = index.data(Qt.DecorationRole)
        if icon is None:
            return
        pixmap = icon.pixmap(QSize(CARD_WIDTH, CARD_HEIGHT))
        size = pixmap.deviceIndependentSize().toSize()
        rect = option.rect
        painter.drawPixmap(rect.x() + (rect.width() - size.width()) // 2,
                           rect.y() + (rect.height() - size.height()) // 2, pixmap)


class ShowcasePanel(QWidget):
    card_clicked = Signal(dict)  # card info popout payload

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._showcases = showcases.load()
        self._pending = {}  # image load token -> list item
        self._generation = 0  # bumped whenever the list is rebuilt (its items are deleted)
        self._editing = False
        self._flipped = False  # showing the cards' backs
        self._radius = CARD_RADIUS  # 0 for "No gaps" showcases

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        bar = QHBoxLayout()
        title = QLabel("Showcases")
        title.setObjectName("screenTitle")
        bar.addWidget(title)
        bar.addSpacing(20)
        self._picker = QComboBox()
        self._picker.setObjectName("sortCombo")
        self._picker.setMinimumWidth(220)
        self._picker.currentIndexChanged.connect(self._on_showcase_picked)
        bar.addWidget(self._picker)
        bar.addStretch()
        self._last_index = -1  # the showcase shown before "+ New showcase…" was picked
        layout.addLayout(bar)

        # The showcase's name — click it to edit; Save locks it again
        name_row = QHBoxLayout()
        self._name_btn = QPushButton()
        self._name_btn.setObjectName("showcaseName")
        self._name_btn.setCursor(Qt.PointingHandCursor)
        self._name_btn.setToolTip("Click to edit this showcase")
        self._name_btn.clicked.connect(lambda: self._set_editing(True))
        name_row.addWidget(self._name_btn)
        self._count = QLabel()
        self._count.setObjectName("resultCount")
        name_row.addWidget(self._count)
        name_row.addSpacing(12)
        self._add_btn = QPushButton("Add cards")
        self._add_btn.clicked.connect(self._add_cards)
        name_row.addWidget(self._add_btn)
        self._rename_btn = self._bar_button(name_row, "Rename", self._rename)
        self._delete_btn = self._bar_button(name_row, "Delete", self._delete)
        name_row.addStretch()
        # Flip: all cards between front and back (proof back / back face /
        # Magic card back) — works locked or editing
        self._flip_btn = QPushButton("Flip to back")
        self._flip_btn.setObjectName("backButton")
        self._flip_btn.clicked.connect(self._flip)
        name_row.addWidget(self._flip_btn)
        name_row.addSpacing(8)
        self._save_btn = QPushButton("Save")
        self._save_btn.setToolTip("Lock the showcase")
        self._save_btn.clicked.connect(lambda: self._set_editing(False))
        name_row.addWidget(self._save_btn)
        layout.addLayout(name_row)

        layout.addWidget(self._build_options_row())

        self._hint = QLabel()
        self._hint.setObjectName("settingsDescription")
        layout.addWidget(self._hint)

        # Cards: a wrapping left-to-right list — drag to reorder
        self._cards = _ShowcaseList()
        self._cards.setObjectName("showcaseCards")
        self._cards.setViewMode(QListView.ListMode)
        self._cards.setFlow(QListView.LeftToRight)
        self._cards.setWrapping(True)
        self._cards.setResizeMode(QListView.Adjust)
        self._cards.setIconSize(QSize(CARD_WIDTH, CARD_HEIGHT))
        self._cards.setDefaultDropAction(Qt.MoveAction)  # drag mode: see _set_editing
        self._cards.setFocusPolicy(Qt.NoFocus)  # no focus outline
        self._cards.setItemDelegate(_CardDelegate(self._cards))
        self._cards.setSelectionMode(QAbstractItemView.SingleSelection)
        self._cards.setVerticalScrollMode(QListView.ScrollPerPixel)
        self._cards.order_changed.connect(self._save_order)
        self._cards.itemClicked.connect(self._on_item_clicked)
        self._cards.setContextMenuPolicy(Qt.CustomContextMenu)
        self._cards.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(self._cards, 1)

        self._reload_picker()

    def _build_options_row(self) -> QWidget:
        """The showcase's settings (editing only, saved per showcase):
        edge-to-edge cards for panoramas, a fixed number per row, whether
        it has a Flip button, and whether it's shown at launch."""
        self._options = QWidget()
        row = QHBoxLayout(self._options)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self._gapless_cb = QCheckBox("No gaps")
        self._gapless_cb.setToolTip("Cards edge to edge — for panorama cards")
        self._gapless_cb.toggled.connect(lambda on: self._set_option("gapless", on))
        row.addWidget(self._gapless_cb)

        per_row_label = QLabel("Per row:")
        per_row_label.setObjectName("filterLabel")
        row.addWidget(per_row_label)
        self._per_row = QComboBox()
        self._per_row.setObjectName("sortCombo")
        self._per_row.addItem("Auto", 0)
        for n in range(1, MAX_PER_ROW + 1):
            self._per_row.addItem(str(n), n)
        self._per_row.setToolTip("Auto fills the width; a number keeps rows fixed (e.g. 3 for a 3×2 panorama)")
        self._per_row.currentIndexChanged.connect(lambda _: self._set_option("per_row", self._per_row.currentData()))
        row.addWidget(self._per_row)
        row.addSpacing(12)

        self._flippable_cb = QCheckBox("Flip button")
        self._flippable_cb.setToolTip("Show a Flip button to see the cards' backs")
        self._flippable_cb.toggled.connect(lambda on: self._set_option("flippable", on))
        row.addWidget(self._flippable_cb)

        self._default_cb = QCheckBox("Show at launch")
        self._default_cb.setToolTip("Open this showcase when the app starts (one showcase at a time)")
        self._default_cb.toggled.connect(self._set_default)
        row.addWidget(self._default_cb)

        row.addStretch()
        return self._options

    @staticmethod
    def _bar_button(bar, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("backButton")
        button.clicked.connect(slot)
        bar.addWidget(button)
        return button

    # ------------------------------------------------------------ state

    def _current(self):
        index = self._picker.currentIndex()
        return self._showcases[index] if 0 <= index < len(self._showcases) else None

    def _reload_picker(self, select_id: str | None = None):
        """Refills the dropdown (keeping / selecting a showcase) and shows it.
        With nothing selected yet: the showcase last picked this session
        (the Home screen is rebuilt on refreshes), else the default one."""
        global _session_showcase_id
        current = self._current()
        select_id = select_id or (current["id"] if current else None) or _session_showcase_id or next(
            (s["id"] for s in self._showcases if s.get("default")), None)
        self._picker.blockSignals(True)
        self._picker.clear()
        for showcase in self._showcases:
            self._picker.addItem(showcase["name"])
        self._picker.addItem(NEW_SHOWCASE_ITEM)  # last: makes a new showcase (see _on_showcase_picked)
        index = next((i for i, s in enumerate(self._showcases) if s["id"] == select_id), 0)
        self._picker.setCurrentIndex(index if self._showcases else -1)
        self._last_index = self._picker.currentIndex()
        self._picker.blockSignals(False)
        current = self._current()
        _session_showcase_id = current["id"] if current else None
        self._editing = False  # callers that keep editing turn it back on
        self._show_current()

    def _on_showcase_picked(self):
        """Dropdown: show another showcase (locked) — or, for the last
        entry, make a new one (the dropdown goes back to the showcase that
        was shown until the new one exists)."""
        global _session_showcase_id
        if self._picker.currentIndex() == len(self._showcases):  # "+ New showcase…"
            self._picker.blockSignals(True)
            self._picker.setCurrentIndex(self._last_index)
            self._picker.blockSignals(False)
            self._new()
            return
        self._last_index = self._picker.currentIndex()
        current = self._current()
        _session_showcase_id = current["id"] if current else None
        self._editing = False
        self._show_current()

    def _set_editing(self, editing: bool):
        """Clicking the name unlocks editing; Save locks again."""
        if self._current() is None:
            return
        self._editing = editing
        self._apply_mode()

    def _apply_mode(self):
        """Shows the edit controls / hint and allows dragging only while
        editing; locked, the showcase is just its name and cards."""
        showcase = self._current()
        editing = self._editing and showcase is not None
        for widget in (self._add_btn, self._rename_btn, self._delete_btn, self._save_btn, self._options):
            widget.setVisible(editing)
        self._cards.setDragDropMode(QAbstractItemView.InternalMove if editing else QAbstractItemView.NoDragDrop)
        self._name_btn.setToolTip("" if editing else "Click to edit this showcase")
        self._name_btn.setProperty("editing", editing)
        self._name_btn.style().unpolish(self._name_btn)  # re-apply [editing] style
        self._name_btn.style().polish(self._name_btn)
        if showcase is None:
            self._hint.setText("Create a showcase to show off cards from your collection — "
                               "pick them, put them in any order, and make as many showcases as you like.")
        elif editing:
            self._hint.setText("Add cards · drag to reorder · right-click to remove · Save when you're done"
                               if showcase["cards"] else "Empty — use Add cards to pick cards from your collection.")
        elif not showcase["cards"]:
            self._hint.setText("Empty — click the showcase's name to add cards.")
        self._hint.setVisible(showcase is None or editing or not showcase["cards"])

    def _show_current(self):
        """Fills the card list from the selected showcase."""
        showcase = self._current()
        has_showcase = showcase is not None
        for widget in (self._picker, self._name_btn, self._count):
            widget.setVisible(has_showcase)
        flippable = has_showcase and bool(showcase["cards"]) and showcase.get("flippable", True)
        self._flip_btn.setVisible(flippable)
        if not flippable and self._flipped:  # back to the fronts
            self._flipped = False
            self._flip_btn.setText("Flip to back")
        self._cards.clear()  # deletes the items — late image results for them are dropped:
        self._pending.clear()
        self._generation += 1
        self._apply_mode()
        if not has_showcase:
            return
        self._name_btn.setText(showcase["name"])
        self._count.setText(plural(len(showcase["cards"]), "card"))

        # layout options
        gapless = showcase.get("gapless", False)
        per_row = showcase.get("per_row", 0)
        for widget, setter in (
            (self._gapless_cb, lambda: self._gapless_cb.setChecked(gapless)),
            (self._per_row, lambda: self._per_row.setCurrentIndex(self._per_row.findData(per_row))),
            (self._flippable_cb, lambda: self._flippable_cb.setChecked(showcase.get("flippable", True))),
            (self._default_cb, lambda: self._default_cb.setChecked(bool(showcase.get("default")))),
        ):
            widget.blockSignals(True)
            setter()
            widget.blockSignals(False)
        gap = 0 if gapless else CARD_GAP
        self._radius = GAPLESS_RADIUS if gapless else CARD_RADIUS
        self._cards.setSpacing(gap)
        cell = QSize(CARD_WIDTH + gap, CARD_HEIGHT + gap)
        if per_row:
            # wide enough for exactly per_row cells (+ frame and a scrollbar).
            # The list puts its spacing on both sides of every cell, so one
            # cell takes cell + 2 * gap; another cell can't fit in the slack.
            frame = 2 * self._cards.frameWidth()
            scrollbar = self._cards.style().pixelMetric(QStyle.PM_ScrollBarExtent)
            self._cards.setMaximumWidth(per_row * (cell.width() + 2 * gap) + frame + scrollbar + 2)
        else:
            self._cards.setMaximumWidth(QWIDGETSIZE_MAX)
        placeholder = QIcon(make_placeholder(CARD_WIDTH, CARD_HEIGHT, self._radius))

        for ref in showcase["cards"]:
            item = QListWidgetItem(placeholder, "")
            item.setData(REF_ROLE, ref)
            item.setToolTip(ref["name"])
            item.setSizeHint(cell)
            self._cards.addItem(item)
            self._load_image(item, ref)

    def _load_image(self, item: QListWidgetItem, ref: dict):
        """Loads the card's front, or its back while flipped. Artist proofs
        replace either side by cache name (see image_cache.get_image_path)."""
        url, cache_name = self._back_source(ref) if self._flipped else (
            scryfall.image_url(ref.get("scryfall_id", "")), scryfall.card_image_cache_name(ref))
        # a late front mustn't land on a flipped card, nor a result on a deleted item
        token = (id(item), self._flipped, self._generation)
        self._pending[token] = item
        ImageLoader.instance().submit(
            token=token,
            url=url,
            cache_name=cache_name,
            width=CARD_WIDTH,
            height=CARD_HEIGHT,
            radius=self._radius,
            on_ready=self._on_image_ready,
        )

    def _back_source(self, ref: dict) -> tuple[str, str]:
        """(url, cache name) of a card's back: its artist proof back if it
        has one, else a double-faced card's back face, else the Magic card back."""
        if artist_proofs.proof_path_for_cache_name(scryfall.back_cache_name(ref)):
            return "", scryfall.back_cache_name(ref)
        entry = showcases.entry_for_ref(ref, self.app.collection.cards)
        if entry and entry["card"].get("layout") in DFC_LAYOUTS:
            return scryfall.back_image_url(ref.get("scryfall_id", "")), scryfall.back_cache_name(ref)
        return scryfall.MAGIC_BACK_URL, scryfall.MAGIC_BACK_CACHE_NAME

    def _on_image_ready(self, token, image):
        item = self._pending.pop(token, None)
        if item is not None and token[1] == self._flipped and token[2] == self._generation:
            item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _flip(self):
        """Flips every card in the showcase (front <-> back)."""
        self._flipped = not self._flipped
        self._flip_btn.setText("Flip to front" if self._flipped else "Flip to back")
        for row in range(self._cards.count()):
            item = self._cards.item(row)
            self._load_image(item, item.data(REF_ROLE))

    def _set_option(self, option: str, value):
        """An options-row change: store it on the showcase and redraw."""
        self._current()[option] = value
        showcases.save(self._showcases)
        self._show_current()

    def _set_default(self, on: bool):
        """Show at launch: at most one default showcase."""
        current = self._current()
        for showcase in self._showcases:
            showcase["default"] = on and showcase is current
        showcases.save(self._showcases)

    def _save_order(self, *_):
        """After a drag: the showcase's cards follow the list's new order."""
        showcase = self._current()
        if showcase is None:
            return
        showcase["cards"] = [self._cards.item(i).data(REF_ROLE) for i in range(self._cards.count())]
        showcases.save(self._showcases)

    # ---------------------------------------------------------- actions

    def _new(self):
        name, ok = QInputDialog.getText(self, "New showcase", "Showcase name:")
        name = name.strip()
        if not ok or not name:
            return
        showcase = showcases.new_showcase(name)
        self._showcases.append(showcase)
        showcases.save(self._showcases)
        self._reload_picker(select_id=showcase["id"])
        self._set_editing(True)  # a new showcase opens ready to fill

    def _rename(self):
        showcase = self._current()
        name, ok = QInputDialog.getText(self, "Rename showcase", "Showcase name:", text=showcase["name"])
        name = name.strip()
        if not ok or not name:
            return
        showcase["name"] = name
        showcases.save(self._showcases)
        self._reload_picker(select_id=showcase["id"])
        self._set_editing(True)  # still editing

    def _delete(self):
        showcase = self._current()
        reply = QMessageBox.question(self, "Delete showcase", f"Delete the showcase \"{showcase['name']}\"?")
        if reply != QMessageBox.Yes:
            return
        self._showcases.remove(showcase)
        showcases.save(self._showcases)
        self._reload_picker()

    def _add_cards(self):
        showcase = self._current()
        dialog = ShowcasePickerDialog(self, self.app, showcase)
        dialog.exec()
        if dialog.added:
            showcases.save(self._showcases)
            self._show_current()  # still editing

    def _on_menu(self, pos):
        """Right-click (while editing): remove the card."""
        item = self._cards.itemAt(pos)
        if item is None or not self._editing:
            return
        menu = QMenu(self)
        remove = menu.addAction(f"Remove {item.data(REF_ROLE)['name']} from the showcase")
        remove.triggered.connect(lambda: self._remove(item))
        menu.exec(self._cards.viewport().mapToGlobal(pos))

    def _remove(self, item: QListWidgetItem):
        for token in [t for t, pending in self._pending.items() if pending is item]:
            del self._pending[token]  # the item is about to be deleted
        self._cards.takeItem(self._cards.row(item))
        self._save_order()
        self._count.setText(plural(self._cards.count(), "card"))

    def _on_item_clicked(self, item: QListWidgetItem):
        """Card info popout for the showcased version — like the
        Collection's (owned printings, decks using this copy)."""
        ref = item.data(REF_ROLE)
        entry = showcases.entry_for_ref(ref, self.app.collection.cards)
        card = entry["card"] if entry else {}
        prices = card.get("prices") or {}
        foil = ref["finish"] in ("foil", "etched")
        payload = {
            "name": ref["name"],
            "set": ref["set"],
            "cn": ref["cn"],
            "price": (prices.get("eur_foil") if foil else None) or prices.get("eur") or 0,
            "image_url": scryfall.image_url(ref.get("scryfall_id", "")),
            "isFoil": ref["finish"] == "foil",
            "finish": ref["finish"],
            "language": ref.get("language", "en"),
        }
        payload["owned_printings"] = availability.owned_printings(self.app.collection, ref["name"])
        payload["used_in_decks"] = availability.used_in_decks_by_printing(self.app.decks, payload)
        self.card_clicked.emit(payload)
