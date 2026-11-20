"""OtherAppsScreen: a hub of smaller tools that don't belong on the main
screens — one card per app (same look as the Settings sections), each
opening its own sub-page with a Back button to the hub.

Apps:
  Purchases     — imported Cardmarket purchases (ui.screens.purchases)
  Token Printer — print sheets of a deck's tokens (ui.screens.token_printer)
  Availability  — which of a deck's cards you own / have free (ui.screens.availability)

To add an app: build its widget (give it a back_requested signal that
returns here), then call self._add_app(...) in __init__.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QStackedWidget, QScrollArea,
)

from ui.components.section_card import SectionCard
from ui.screens.purchases import PurchasesScreen
from ui.screens.token_printer import TokenPrinterScreen
from ui.screens.availability import AvailabilityScreen


class OtherAppsScreen(QWidget):
    card_clicked = Signal(dict)  # forwarded from apps that show clickable cards
    export_requested = Signal(list)  # forwarded from the Availability Checker's Export

    def __init__(self, app):
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        layout.addWidget(self._pages)

        self._hub, self._hub_layout = self._build_hub()
        self._pages.addWidget(self._hub)

        self.purchases = PurchasesScreen(app)
        self.purchases.card_clicked.connect(self.card_clicked.emit)
        self._add_app(
            "Purchases",
            "Import Cardmarket purchase PDFs, browse them like your collection, mark them "
            "received, and export them for Moxfield.",
            "Open purchases",
            self.purchases,
        )

        self.token_printer = TokenPrinterScreen(app)
        self._add_app(
            "Token Printer",
            "Pick a deck and get a Word document with its tokens at real card size, ready to "
            "print and cut — choose how many of each.",
            "Open token printer",
            self.token_printer,
        )

        self.availability = AvailabilityScreen(app)
        self.availability.card_clicked.connect(self.card_clicked.emit)
        self.availability.export_requested.connect(self.export_requested.emit)
        self._add_app(
            "Availability Checker",
            "Paste a Moxfield deck link to see which of its cards you own and have free, which "
            "are already in another active deck, and which you're missing.",
            "Open availability checker",
            self.availability,
        )

        self._hub_layout.addStretch()

    def _build_hub(self):
        """The hub page: title, then one card per app (added by _add_app).
        Scrollable, for when there are many apps."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(20)

        title = QLabel("Other Apps")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")  # transparent, borderless
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll, outer

    def _add_app(self, name: str, description: str, button_text: str, widget: QWidget):
        """Adds an app: a card on the hub whose button opens `widget`
        (a sub-page; its back_requested signal returns to the hub)."""
        self._pages.addWidget(widget)
        widget.back_requested.connect(self.show_hub)

        section = SectionCard(name, description)
        section.add_button(button_text, lambda: self._pages.setCurrentWidget(widget))
        self._hub_layout.addWidget(section)

    def show_hub(self):
        self._pages.setCurrentWidget(self._hub)
