"""DeckMakerScreen: build new commander decks from cards in the
collection. Three pages in a stack:

1. Start — "Create new deck" (built here).
2. Choose commander — CommanderPage (commander_page.py).
3. Build deck — BuildPage (build_page.py), which holds the deck being
   built.

This screen moves between them, starts / opens / closes decks, and is
what MainWindow talks to (open_draft, reload_collection, refresh_usage,
reload_images, forget_saved_deck; card_clicked, deck_saved).
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from app import MTGApp
from card_fields import plural
from models.deck_draft import DeckDraft

from .build_page import BuildPage
from .commander_page import CommanderPage
from .helpers import IS_COMMANDER, IS_COMMANDER_LEGAL, CardUsage


class DeckMakerScreen(QWidget):
    card_clicked = Signal(dict)  # card info popout payload
    deck_saved = Signal()  # a deck was written to disk — MainWindow reloads the deck lists

    def __init__(self, app: MTGApp):
        """Builds the three pages; starts on the Start page."""
        super().__init__()
        self.app = app
        # which copies other active decks use — never counting the deck being edited
        self.usage = CardUsage(app, own_deck_id=lambda: self.draft.deck_id if self.draft else None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        layout.addWidget(self._pages)

        self._start_page = self._build_start_page()

        self._commander_page = CommanderPage(self.usage)
        self._commander_page.picked.connect(self._on_commander_picked)
        self._commander_page.back_requested.connect(self._on_commander_back)

        self._build_page = BuildPage(app, self.usage)
        self._build_page.card_clicked.connect(self.card_clicked.emit)
        self._build_page.deck_saved.connect(self.deck_saved.emit)
        self._build_page.change_commander_requested.connect(
            lambda: self._pages.setCurrentWidget(self._commander_page))
        self._build_page.closed.connect(lambda: self._pages.setCurrentWidget(self._start_page))

        for page in (self._start_page, self._commander_page, self._build_page):
            self._pages.addWidget(page)

        self.reload_collection()

    @property
    def draft(self) -> DeckDraft | None:
        """The deck being built (held by the build page), or None."""
        return self._build_page.draft

    # ------------------------------------------------------ called by MainWindow

    def reload_collection(self):
        """Re-reads everything derived from app.collection — called by
        MainWindow after a refresh/login/cache-clear instead of
        rebuilding this screen, so a draft in progress isn't lost."""
        cards = self.app.collection.cards
        self.usage.reload_collection()
        self._commander_page.set_candidates([e for e in cards if IS_COMMANDER(e)])
        self._build_page.set_pool([e for e in cards if IS_COMMANDER_LEGAL(e)])

    def open_draft(self, draft: DeckDraft, left_out: list[str]) -> bool:
        """Opens `draft` (from models.deck_editing — an existing deck, or a
        copy of one) on the build page. Asks first if another draft is open.
        left_out: cards that couldn't be added, shown in a message. Returns
        False if the user kept the current draft instead."""
        if self.draft is not None:
            reply = QMessageBox.question(
                self, "Replace deck",
                f"You're working on \"{self.draft.name}\" in the Deck Maker. "
                f"Open \"{draft.name}\" instead? Unsaved changes are lost.",
            )
            if reply != QMessageBox.Yes:
                return False
        if draft.deck_id:
            feedback = f"Editing \"{draft.name}\" — Save deck updates it"
        else:
            feedback = f"Editing a copy — Save deck creates \"{draft.name}\" as your own deck"
        self._build_page.load(draft, feedback)
        self._pages.setCurrentWidget(self._build_page)
        if left_out:
            QMessageBox.information(
                self, "Some cards left out",
                f"{plural(len(left_out), 'card')} couldn't be added — the Deck Maker only uses "
                "cards from your collection:\n\n" + "\n".join(left_out),
            )
        return True

    def forget_saved_deck(self, deck_id: str):
        """A saved deck was deleted — see BuildPage.forget_saved_deck."""
        self._build_page.forget_saved_deck(deck_id)

    def reload_images(self):
        """Reloads card images (artist proofs changed)."""
        self._commander_page.reload_images()
        self._build_page.reload_images()

    def refresh_usage(self):
        """Re-checks which cards are used in other decks — called by
        MainWindow once deck contents finish loading in the background."""
        self._build_page.refresh_usage()

    # ------------------------------------------------------------ pages

    def _build_start_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(16)

        title = QLabel("Deck Maker")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        description = QLabel(
            "Build a new Commander deck from cards in your collection. "
            "You start by choosing the commander."
        )
        description.setObjectName("settingsDescription")
        description.setWordWrap(True)
        outer.addWidget(description)

        button_row = QHBoxLayout()
        create_btn = QPushButton("Create new deck")
        create_btn.clicked.connect(self._start_new_deck)
        button_row.addWidget(create_btn)
        button_row.addStretch()
        outer.addLayout(button_row)

        outer.addStretch()
        return page

    def _start_new_deck(self):
        """Start page → Choose commander, for a fresh draft."""
        self._build_page.draft = None
        self._commander_page.reset_search()
        self._pages.setCurrentWidget(self._commander_page)

    def _on_commander_back(self):
        """Back from Choose commander: to the draft if one is in
        progress (i.e. we came from "Change commander"), else to Start."""
        self._pages.setCurrentWidget(self._build_page if self.draft else self._start_page)

    def _on_commander_picked(self, entry: dict):
        """A commander was clicked: starts a new draft with it, or swaps
        the commander of the draft in progress."""
        if self.draft is None:
            self._build_page.load(DeckDraft(entry))
        else:
            self._build_page.change_commander(entry)
        self._pages.setCurrentWidget(self._build_page)
