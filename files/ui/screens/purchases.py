"""PurchasesScreen (an app on the Other Apps page): imported Cardmarket
purchases — the Import button reads a purchase PDF, see cardmarket.py.
A list page, and a detail page that is the Collection screen showing just
that purchase's cards, plus Moxfield export and delete buttons. Cards the
seller couldn't send can be removed (right-click a card) and restored,
and a purchase can be marked received (green check in the list).
"""

from PySide6.QtCore import Qt, Signal, QSize, QPoint
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QStackedWidget, QFileDialog, QMessageBox, QMenu,
)

from datetime import date
from pathlib import Path

import cardmarket
from card_fields import plural
from models import purchases
from printing import entry_printing_key
from ui.components.section_card import back_button
from ui.background import run_in_background
from ui.icon_utils import check_icon
from ui.screens.collection import CollectionScreen
from ui import theme

ROW_HEIGHT = 34  # purchase list row
RECEIVED_COLOR = theme.WIN


def purchase_summary(p: dict) -> str:
    """One line describing a purchase: name · seller · date · cards · total."""
    parts = [p["name"]]
    if p.get("seller"):
        parts.append(p["seller"])
    if p.get("date"):
        parts.append(p["date"])
    parts.append(plural(sum(e["quantity"] for e in purchases.received_entries(p)), "card"))
    if p.get("total") is not None:
        parts.append(f"€{p['total']:,.2f}")
    return "  ·  ".join(parts)


class PurchasesScreen(QWidget):
    card_clicked = Signal(dict)  # forwarded from the detail page's card grid
    back_requested = Signal()  # list page's Back button (to the Other Apps page)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._detail = None  # the CollectionScreen of the open purchase
        self._purchase = None
        self._bg_tasks = []  # keeps background tasks alive — see ui/background.py

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        layout.addWidget(self._pages)

        self._list_page = self._build_list_page()
        self._detail_page = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_page)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(0)
        self._pages.addWidget(self._list_page)
        self._pages.addWidget(self._detail_page)

        self.reload()

    # ------------------------------------------------------------ list
    def _build_list_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(16)

        top_bar = QHBoxLayout()
        back_btn = back_button(self.back_requested.emit)
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        outer.addLayout(top_bar)

        title_row = QHBoxLayout()
        title = QLabel("Purchases")
        title.setObjectName("screenTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self._import_btn = QPushButton("Import purchase PDF…")
        self._import_btn.setToolTip(
            "A Cardmarket purchase PDF. If its ArticlesFromShipment<order number>.csv is in "
            "the same folder, card and foil counts are checked against it.")
        self._import_btn.clicked.connect(self._on_import)
        title_row.addWidget(self._import_btn)
        title_container = QWidget()
        title_container.setLayout(title_row)
        title_container.setMaximumWidth(760)  # button lines up with the list's right edge
        title_row.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(title_container)

        self._empty_label = QLabel(
            "No purchases yet. Import a Cardmarket purchase PDF — every card is looked up on "
            "Scryfall, and the purchase can then be exported for Moxfield."
        )
        self._empty_label.setObjectName("settingsDescription")
        self._empty_label.setWordWrap(True)
        outer.addWidget(self._empty_label)

        self._list = QListWidget()
        self._list.setObjectName("deckList")
        self._list.setCursor(Qt.PointingHandCursor)
        self._list.setMaximumWidth(760)
        self._list.setIconSize(QSize(18, 18))
        self._list.itemClicked.connect(lambda item: self.show_purchase(item.data(Qt.UserRole)))
        outer.addWidget(self._list)

        outer.addStretch()  # keep everything at the top
        return page

    def reload(self):
        """Re-reads the saved purchases into the list (and goes back to it)."""
        self._list.clear()
        all_purchases = purchases.list_all()
        for p in all_purchases:
            item = QListWidgetItem(purchase_summary(p))
            # blank icon when not received, so the text stays aligned
            item.setIcon(check_icon(RECEIVED_COLOR if p.get("received") else None))
            if p.get("received"):
                item.setToolTip(f"Received {p.get('received_at') or ''}".strip())
            item.setData(Qt.UserRole, p["id"])
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            self._list.addItem(item)
        # As tall as its rows (scrolls past ~15), not the whole page
        rows = min(len(all_purchases), 15)
        self._list.setFixedHeight(rows * ROW_HEIGHT + 16)
        self._empty_label.setVisible(not all_purchases)
        self._list.setVisible(bool(all_purchases))
        self._show_list()

    def _show_list(self):
        self._pages.setCurrentWidget(self._list_page)

    # ---------------------------------------------------------- detail
    def show_purchase(self, purchase_id: str):
        """Opens a purchase's detail page (a CollectionScreen of its cards)."""
        p = purchases.load(purchase_id)
        if p is None:
            self.reload()
            return
        self._purchase = p

        if self._detail is not None:
            self._detail_layout.removeWidget(self._detail)
            self._detail.deleteLater()

        self._detail = CollectionScreen(
            self.app, cards=purchases.received_entries(p), title=p["name"], refreshable=False,
            extra_stats=self._extra_stats(p),
        )
        self._detail.card_clicked.connect(self.card_clicked.emit)
        self._detail.entry_menu_requested.connect(self._on_card_menu)

        # Back button before the title; export / delete after it
        header = self._detail._header_layout
        back_btn = back_button(self.reload)  # reload: card counts may have changed
        header.insertWidget(0, back_btn)
        header.insertSpacing(1, 16)
        self._received_btn = QPushButton()
        self._received_btn.clicked.connect(self._toggle_received)
        header.addWidget(self._received_btn)
        self._update_received_button()

        self._restore_btn = QPushButton("Restore")
        self._restore_btn.setToolTip("Put back every card removed from this purchase")
        self._restore_btn.clicked.connect(self._restore_removed)
        header.addWidget(self._restore_btn)
        for text, tip, slot in (
            ("Export CSV…", "Save a Moxfield collection import CSV", self._export_csv),
            ("Copy list", "Copy a card list for a Moxfield deck / binder import", self._copy_list),
            ("Delete", "Delete this purchase", self._delete),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            header.addWidget(btn)
        self._update_restore_button()

        self._detail_layout.addWidget(self._detail)
        self._pages.setCurrentWidget(self._detail_page)

    @staticmethod
    def _extra_stats(p: dict) -> str:
        """Purchase-specific stats lines (HTML) under the collection stats."""
        lines = []
        paid = []
        if p.get("article_value") is not None:
            paid.append(f"cards €{p['article_value']:,.2f}")
        if p.get("shipping") is not None:
            paid.append(f"shipping €{p['shipping']:,.2f}")
        if p.get("total") is not None:
            paid.append(f"<b>total €{p['total']:,.2f}</b>")
        if paid:
            lines.append("Paid: " + " · ".join(paid))
        meta = [x for x in (p.get("seller") and f"Seller: {p['seller']}",
                            p.get("date") and f"Date: {p['date']}") if x]
        if p.get("received"):
            meta.append(f"<span style='color:{RECEIVED_COLOR}'>✓ Received"
                        + (f" {p['received_at']}" if p.get("received_at") else "") + "</span>")
        if meta:
            lines.append(" · ".join(meta))
        removed = [(e["card"]["name"], e["removed"]) for e in p["entries"] if e.get("removed")]
        if removed:
            count = sum(n for _, n in removed)
            refund = sum(e["purchasePrice"] * e["removed"] for e in p["entries"] if e.get("removed"))
            names = ", ".join(f"{n}x {name}" if n > 1 else name for name, n in removed)
            lines.append(f"Removed (not received): {plural(count, 'card')}, €{refund:,.2f} — {names}")
        unresolved = [e["card"]["name"] for e in purchases.received_entries(p) if e.get("unresolved")]
        if unresolved:
            lines.append("Not found on Scryfall (no image / price): " + ", ".join(unresolved))
        if p.get("csv_check"):
            lines.append(p["csv_check"])
        if p.get("skipped"):
            lines.append(f"{plural(len(p['skipped']), 'PDF line')} couldn't be read when importing")
        return "<br><br>" + "<br>".join(lines) if lines else ""

    # --------------------------------------------------------- import
    def _on_import(self):
        """Import button: pick a PDF, then parse + look it up in the
        background (the Scryfall lookups take a few seconds)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Cardmarket purchase PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        self._import_btn.setEnabled(False)
        self._import_btn.setText("Importing…")
        run_in_background(
            lambda: cardmarket.import_purchase(Path(path)),
            self._bg_tasks,
            on_finished=self._on_imported,
            on_failed=self._on_import_failed,
        )

    def _reset_import_button(self):
        self._import_btn.setEnabled(True)
        self._import_btn.setText("Import purchase PDF…")

    def _on_imported(self, purchase: dict):
        """Background-task callback: saves the purchase (asking first if
        that order was imported before), opens it, and warns about
        anything that didn't import cleanly."""
        self._reset_import_button()
        if purchases.exists(purchase["id"]):
            reply = QMessageBox.question(
                self, "Already imported",
                f"{purchase['name']} was imported before. Replace it? (Removed cards and "
                "the received mark are reset.)")
            if reply != QMessageBox.Yes:
                return
        purchases.save(purchase)
        self.reload()
        self.show_purchase(purchase["id"])

        problems = []
        if purchase.get("csv_check") and "MISMATCH" in purchase["csv_check"]:
            problems.append(purchase["csv_check"])
        unresolved = [e["card"]["name"] for e in purchase["entries"] if e.get("unresolved")]
        if unresolved:
            problems.append("Not found on Scryfall (kept without image / price):\n    "
                            + "\n    ".join(unresolved))
        if purchase.get("skipped"):
            problems.append("Could not read these PDF lines (not imported):\n    "
                            + "\n    ".join(purchase["skipped"]))
        if problems:
            QMessageBox.warning(self, "Imported with warnings", "\n\n".join(problems))

    def _on_import_failed(self, message: str):
        """Background-task callback: unreadable PDF, Scryfall down, ..."""
        self._reset_import_button()
        QMessageBox.warning(self, "Import failed", message)

    # ------------------------------------------------------- received
    def _toggle_received(self):
        """Marks the purchase received (today) / not received."""
        p = self._purchase
        if p.get("received"):
            p["received"] = False
            p.pop("received_at", None)
        else:
            p["received"] = True
            p["received_at"] = date.today().isoformat()
        purchases.save(p)
        self._detail.set_cards(purchases.received_entries(p), self._extra_stats(p))
        self._update_received_button()

    def _update_received_button(self):
        """"Mark received", or a green "Received" (click to undo)."""
        if self._purchase.get("received"):
            self._received_btn.setText("Received")
            self._received_btn.setIcon(check_icon(theme.PAGE_BG))
            self._received_btn.setToolTip("Click to mark as not received")
            self._received_btn.setStyleSheet(
                f"QPushButton {{ background-color: {RECEIVED_COLOR}; color: #1a1a1a; }}")
        else:
            self._received_btn.setText("Mark received")
            self._received_btn.setIcon(QIcon())  # no blank icon — it would push the text off-center
            self._received_btn.setToolTip("The cards have arrived")
            self._received_btn.setStyleSheet("")

    # ------------------------------------------------- removing cards
    def _matching(self, tile: dict) -> list:
        """The purchase's stored entries a grid tile stands for (a tile is
        one printing + finish, all languages — see merge_languages)."""
        key = entry_printing_key(tile)[:3]
        return [e for e in self._purchase["entries"] if entry_printing_key(e)[:3] == key]

    def _on_card_menu(self, tile: dict, pos: QPoint):
        """Right-click on a card: remove one copy / all copies."""
        name = tile["card"]["name"]
        menu = QMenu(self)
        menu.addAction(f"Remove 1 {name} (not received)")  # any pick but "all" removes one
        remove_all = None
        if tile["quantity"] > 1:
            remove_all = menu.addAction(f"Remove all {tile['quantity']} copies")
        picked = menu.exec(pos)
        if picked is None:
            return

        entries = self._matching(tile)
        if picked is remove_all:
            for e in entries:
                e["removed"] = e["quantity"]
        else:
            e = next(e for e in reversed(entries) if e["quantity"] - e.get("removed", 0) > 0)
            e["removed"] = e.get("removed", 0) + 1
        self._save_and_refresh()

    def _restore_removed(self):
        for e in self._purchase["entries"]:
            e.pop("removed", None)
        self._save_and_refresh()

    def _save_and_refresh(self):
        purchases.save(self._purchase)
        self._detail.set_cards(purchases.received_entries(self._purchase),
                               self._extra_stats(self._purchase))
        self._update_restore_button()

    def _update_restore_button(self):
        self._restore_btn.setVisible(any(e.get("removed") for e in self._purchase["entries"]))

    # ---------------------------------------------------------- export
    def _export_csv(self):
        p = self._purchase
        path, _ = QFileDialog.getSaveFileName(
            self, "Export for Moxfield", f"{p['name'].replace('#', '')}_moxfield_collection.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(cardmarket.moxfield_csv(purchases.received_entries(p)))
        QMessageBox.information(self, "Exported",
                                f"Saved. Import it on Moxfield under Collection → Import (CSV).\n\n{path}")

    def _copy_list(self):
        QGuiApplication.clipboard().setText(
            cardmarket.moxfield_list(purchases.received_entries(self._purchase)))
        QMessageBox.information(self, "Copied",
                                "Card list copied — paste it into a Moxfield deck or binder's Import box.")

    def _delete(self):
        p = self._purchase
        if QMessageBox.question(self, "Delete purchase",
                                f"Delete \"{p['name']}\"? This can't be undone.") != QMessageBox.Yes:
            return
        purchases.delete(p["id"])
        self.reload()
