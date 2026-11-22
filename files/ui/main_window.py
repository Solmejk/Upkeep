"""MainWindow: the app's top-level window. Owns the sidebar, the screen
stack (Home/Decks/Collection/Deck Maker/Game Tracker/Other Apps/Settings + the on-demand
DeckDetail screen), and the two shared popouts (CardModal, ExportModal).
Also owns every cross-screen flow that doesn't belong to a single
screen: login, logout, cache-clear, Moxfield refresh, and rebuilding the
data-snapshotting screens after any of those.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QMessageBox, QInputDialog,
)

from app import MTGApp
from models import deck_editing, local_decks
from models.user import User
from ui.sidebar import Sidebar
from ui.screens.home import HomeScreen
from ui.screens.decks import DecksScreen
from ui.screens.deck_detail import DeckDetailScreen
from ui.screens.collection import CollectionScreen
from ui.screens.settings import SettingsScreen
from ui.screens.deck_maker import DeckMakerScreen
from ui.screens.other_apps import OtherAppsScreen
from ui.screens.game_tracker import GameTrackerScreen
from ui.components.card_modal import CardModal
from ui.components.export_modal import DeckExportModal, ExportModal
from ui.components.player_modal import PlayerModal
from ui.components.tracker_deck_modal import TrackerDeckModal
from ui.background import run_in_background
import clear_cache
import scryfall
import session
import sync
from image_prefetch import ImagePrefetcher


class MainWindow(QMainWindow):
    def __init__(self, app: MTGApp):
        """Builds every screen, wires up navigation and cross-screen
        signals, and kicks off the background deck-content load. app:
        the MTGApp facade, already loaded (or logged-out) by main.py."""
        super().__init__()
        self.app = app
        self.setWindowTitle("MTG Collection Manager")
        self.resize(1100, 750)
        self._bg_tasks = []  # keeps background tasks alive — see ui/background.py
        self._login_in_progress = False
        self._refresh_in_progress = False
        self._image_prefetcher = ImagePrefetcher()

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar(app)
        self.stack = QStackedWidget()

        self.home_screen = self._new_home_screen()
        self.decks_screen = self._new_decks_screen()
        self.collection_screen = self._new_collection_screen()
        self.deck_maker_screen = DeckMakerScreen(app)
        self.game_tracker_screen = GameTrackerScreen(app)
        self.other_apps_screen = OtherAppsScreen(app)
        self.settings_screen = SettingsScreen(app)

        self.deck_detail_screen = DeckDetailScreen(app)

        self._add_page("Home",         self.home_screen)
        self._add_page("Decks",        self.decks_screen)
        self._add_page("Collection",   self.collection_screen)
        self._add_page("Deck Maker",   self.deck_maker_screen)
        self._add_page("Game Tracker", self.game_tracker_screen)
        self._add_page("Other Apps",   self.other_apps_screen)
        self._add_page("Settings",     self.settings_screen)

        self.stack.addWidget(self.deck_detail_screen)

        self.sidebar.nav_changed.connect(self.stack.setCurrentIndex)
        self.sidebar.set_current(0)
        self.sidebar.login_requested.connect(self._on_login_requested)

        self.deck_detail_screen.back_requested.connect(self._close_deck_detail)
        self.deck_detail_screen.delete_requested.connect(self._delete_deck)
        self.deck_detail_screen.edit_requested.connect(self._edit_deck)
        # confirmed languages change which exact copies count as used
        self.deck_detail_screen.languages_changed.connect(self.deck_maker_screen.refresh_usage)

        # Artist proofs changed (settings screen): show the new images
        self.settings_screen.proofs_changed.connect(self._on_proofs_changed)

        # Full Moxfield refresh (settings screen: Sync → Refresh all) — the
        # settings screen isn't rebuilt, so this is connected once
        self.settings_screen.refresh_requested.connect(
            lambda: self._start_refresh(sync.refresh_all, "Settings", "settings_screen"))

        # Cache clearing (settings screen)
        self.settings_screen.clear_cache_requested.connect(self._clear_cache)

        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.stack, 1)

        self.setCentralWidget(root)

        # Card modal — shared by every screen that shows a clickable card
        self.card_modal = CardModal(self)
        self.deck_detail_screen.card_clicked.connect(self.card_modal.show_card)
        self.deck_detail_screen.tracker_deck_clicked.connect(self._show_tracker_deck)
        self.card_modal.token_printing_changed.connect(self._on_token_printing_changed)
        self.deck_maker_screen.card_clicked.connect(self.card_modal.show_card)
        self.other_apps_screen.card_clicked.connect(self.card_modal.show_card)
        self.deck_maker_screen.deck_saved.connect(self._rebuild_data_screens)  # show it on Decks etc.

        # Export modal (availability screen)
        self.export_modal = ExportModal(self)
        self.other_apps_screen.export_requested.connect(self.export_modal.show_export)  # Availability Checker

        # Player popout (Game Tracker: click a player's name)
        self.player_modal = PlayerModal(self)
        self.game_tracker_screen.player_clicked.connect(self._show_player)
        self.tracker_deck_modal = TrackerDeckModal(self)
        self.game_tracker_screen.deck_clicked.connect(self._show_tracker_deck)

        # Moxfield export modal (Deck Maker decks, from the deck detail screen)
        self.deck_export_modal = DeckExportModal(self)
        self.deck_detail_screen.export_requested.connect(self.deck_export_modal.show_export)

        QTimer.singleShot(50, self._lazy_load_decks)

    def _add_page(self, name: str, widget: QWidget):
        """Registers `widget` as a navigable screen: adds a sidebar entry
        labeled `name` and a matching page in the stack (same index in
        both, since Sidebar.nav_changed drives stack.setCurrentIndex)."""
        self.sidebar.add_item(name)
        self.stack.addWidget(widget)

    # ------------------------------------------------- rebuilt screens
    # Home, Decks and Collection snapshot the app's data when they're built,
    # so they're replaced (not updated) after refreshes, logins and cache
    # clears. Each is built AND wired in exactly one place — its factory —
    # so a rebuilt screen can never come back missing a connection.

    def _new_home_screen(self) -> HomeScreen:
        screen = HomeScreen(self.app)
        screen.card_clicked.connect(self._show_card)          # a showcase card
        screen.player_clicked.connect(self._show_player)      # your Elo
        screen.deck_clicked.connect(self._show_tracker_deck)  # your best deck
        return screen

    def _new_decks_screen(self) -> DecksScreen:
        screen = DecksScreen(self.app)
        screen.deck_selected.connect(self._open_deck_detail)
        screen.delete_requested.connect(self._delete_deck)
        screen.deck_imported.connect(self._on_deck_imported)
        screen.refresh_requested.connect(
            lambda: self._start_refresh(sync.refresh_decks, "Decks page", "decks_screen"))
        return screen

    def _new_collection_screen(self) -> CollectionScreen:
        screen = CollectionScreen(self.app)
        screen.card_clicked.connect(self._show_card)
        screen.refresh_requested.connect(
            lambda: self._start_refresh(sync.refresh_collection, "Collection page", "collection_screen"))
        return screen

    def _show_card(self, card: dict):
        """Opens the card popout (a method, so screens built before the
        popout exists can connect to it)."""
        self.card_modal.show_card(card)

    def _open_deck_detail(self, deck):
        """Slot for DecksScreen.deck_selected: ensures `deck`'s contents
        are loaded (cache-only first, then a forced fetch if the cache
        was empty/cleared) and switches to the detail screen."""
        if not deck.cards:        # ← not loaded yet
            deck.load()
            if not deck.cards:     # cache missing (e.g. cache was cleared) — fetch it
                try:
                    deck.load(force=True)
                except Exception as e:
                    QMessageBox.warning(self, "Load failed", str(e))
        self.deck_detail_screen.show_deck(deck)
        self.stack.setCurrentWidget(self.deck_detail_screen)

    def _close_deck_detail(self):
        """Slot for DeckDetailScreen.back_requested: returns to the Decks
        screen. The deck's active/archived flag may have been toggled on
        the detail screen, so the Decks grid (active-only filter) and
        Home (active/archived counts) are rebuilt to reflect it."""
        self.decks_screen.rebuild_grid()
        self._replace_screen("home_screen", self._new_home_screen())
        self.stack.setCurrentWidget(self.decks_screen)

    def _show_tracker_deck(self, deck_key):
        """Game Tracker / Home: a deck was clicked — its popout."""
        if self.stack.currentWidget() is not self.game_tracker_screen:
            self.game_tracker_screen.reload()  # fresh data (e.g. clicked from Home)
        self.tracker_deck_modal.show_deck(
            self.game_tracker_screen.tracker, deck_key, self.game_tracker_screen.player_label)

    def _show_player(self, player_id: str):
        """Game Tracker / Home: a player's name was clicked — their popout."""
        if self.stack.currentWidget() is not self.game_tracker_screen:
            self.game_tracker_screen.reload()  # fresh data (e.g. clicked from Home)
        tracker = self.game_tracker_screen.tracker
        player = tracker.players[player_id]
        self.player_modal.show_player(tracker, player_id, self.app.is_me(player))

    def _on_deck_imported(self, deck_id: str):
        """A decklist was imported (Decks screen): reload the deck lists so
        it shows up everywhere, then open it."""
        self._rebuild_data_screens()
        deck = next((d for d in self.app.decks if d.deck_id == deck_id), None)
        if deck is not None:
            self._open_deck_detail(deck)

    def _on_token_printing_changed(self):
        """A token's default printing changed (card popup): redraw the
        open deck's Tokens section with it."""
        if self.deck_detail_screen.deck is not None:
            self.deck_detail_screen.rebuild_sections()

    def _on_proofs_changed(self):
        """Artist proofs were added / changed / removed: rebuild the data
        screens (fresh image loads) and reload the Deck Maker's grids."""
        self._rebuild_data_screens()
        self.deck_maker_screen.reload_images()

    def _edit_deck(self, deck):
        """Slot for DeckDetailScreen.edit_requested: opens the deck in the
        Deck Maker — the deck itself for Deck Maker decks (saving updates
        it), a new copy for website imports."""
        try:
            draft, left_out = deck_editing.draft_from_deck(deck, self.app.collection.cards, copy=deck.is_imported)
        except deck_editing.EditError as e:
            QMessageBox.warning(self, "Can't edit deck", str(e))
            return
        if self.deck_maker_screen.open_draft(draft, left_out):
            self.sidebar.set_current(self.stack.indexOf(self.deck_maker_screen))

    def _delete_deck(self, deck):
        """Slot for delete_requested (Decks tile menu / DeckDetail button):
        after confirming, deletes a Deck Maker deck's file and reloads the
        deck lists. Website imports can't be deleted (ignored)."""
        if deck is None or deck.is_imported:
            return
        reply = QMessageBox.question(
            self, "Delete deck", f"Delete \"{deck.name}\"? This can't be undone.",
        )
        if reply != QMessageBox.Yes:
            return
        local_decks.delete(deck.deck_id)
        self.deck_maker_screen.forget_saved_deck(deck.deck_id)
        if self.stack.currentWidget() is self.deck_detail_screen:
            self.stack.setCurrentWidget(self.decks_screen)
        self._rebuild_data_screens()

    def _start_refresh(self, job, source: str, screen_attr: str):
        """Runs a sync.refresh_* job for the current user in the
        background. source: label for the sync log. screen_attr: the
        screen whose button was clicked (e.g. "decks_screen") — looked
        up by name since the screen object is replaced on rebuild.
        Ignored while another refresh is running; warns if logged out."""
        if not self.app.is_logged_in:
            QMessageBox.information(self, "Not logged in", "Log in first via the sidebar avatar.")
            return
        if self._refresh_in_progress:
            return
        self._refresh_in_progress = True
        self._refreshing_screen_attr = screen_attr
        getattr(self, screen_attr).set_refresh_enabled(False)
        user = self.app.user
        run_in_background(
            lambda: job(user, source),
            self._bg_tasks,
            on_finished=self._on_refresh_finished,
            on_failed=self._on_refresh_failed,
        )

    def _on_refresh_finished(self, _result):
        """Background-task callback: rebuilds the data screens to show
        the freshly-fetched data (the rebuilt screens come with their
        refresh buttons enabled). _result is unused (jobs return None)."""
        self._refresh_in_progress = False
        self._rebuild_data_screens()
        self.settings_screen.set_refresh_enabled(True)  # not rebuilt, unlike the others

    def _on_refresh_failed(self, message: str):
        """Background-task callback: re-enables the refresh button and
        surfaces the error. message: str(exception) from the failed fetch."""
        self._refresh_in_progress = False
        getattr(self, self._refreshing_screen_attr).set_refresh_enabled(True)
        QMessageBox.warning(self, "Refresh failed", message)

    def _on_login_requested(self):
        """Slot for Sidebar.login_requested (clicking the avatar/name):
        prompts for a Moxfield username and, if one's entered, force-
        fetches it in the background. Pre-fills the prompt with the
        current username, so this doubles as "switch account". Ignored
        while a login is already in flight."""
        if self._login_in_progress:
            return
        current = self.app.username or ""
        username, ok = QInputDialog.getText(
            self, "Log in to Moxfield", "Moxfield username:", text=current,
        )
        if not ok:
            return
        username = username.strip()
        if not username:
            return

        self._login_in_progress = True
        self._pending_login_username = username
        self.sidebar.set_login_pending(True)
        run_in_background(
            lambda: self._fetch_user(username),
            self._bg_tasks,
            on_finished=self._on_login_finished,
            on_failed=self._on_login_failed,
        )

    @staticmethod
    def _fetch_user(username: str) -> User:
        """Background-task body for login: builds and force-loads a new
        User for `username`. Runs off to the side rather than mutating
        self.app directly — if the fetch fails partway (bad username,
        network hiccup), a working prior session must not be clobbered
        with a half-loaded empty one. Raises on failure (caught by
        run_in_background, routed to _on_login_failed)."""
        user = User(username)
        sync.refresh_all(user, "Login")
        return user

    def _on_login_finished(self, user: User):
        """Background-task callback for a successful login: commits the
        fetched user, persists the session, and rebuilds the data
        screens. user: the fully-loaded User from _fetch_user."""
        self._login_in_progress = False
        self.app.set_user(user)
        session.save_username(self._pending_login_username)
        self._rebuild_data_screens()

    def _on_login_failed(self, message: str):
        """Background-task callback for a failed login: restores the
        sidebar's prior display (untouched by the failed attempt) and
        surfaces the error. message: str(exception) from the failed fetch."""
        self._login_in_progress = False
        self.sidebar.set_login_pending(False)
        self.sidebar.refresh_profile(self.app)  # untouched by the failed attempt — just restore its display
        QMessageBox.warning(self, "Login failed", message)

    def _clear_cache(self, targets: list):
        """Slot for SettingsScreen.clear_cache_requested: clears each
        selected cache category on disk, then rebuilds the data screens
        to reflect it. targets: list of "collection"/"decks"/"profile"/
        "images". Clearing "profile" also logs the user out — see the
        comment below for why that's necessary."""
        for target in targets:
            if target == "collection":
                clear_cache.clear_collection()
            elif target == "decks":
                clear_cache.clear_decks()
            elif target == "profile":
                clear_cache.clear_profile()
            elif target == "images":
                clear_cache.clear_images()

        if "profile" in targets:
            # The username itself lives in session.py, independent of the
            # user_<name>.json cache file — clearing profile data without
            # this would leave the sidebar showing the old username with no
            # way to tell the app has actually forgotten everything about them.
            self.app.logout()
            session.clear_username()

        self._rebuild_data_screens()

    def _rebuild_data_screens(self):
        """Reflect whatever is currently on disk (after a cache clear or a
        Moxfield refresh) without requiring an app restart. Home, Decks, and
        Collection each snapshot app data once at construction time, so they
        need to be rebuilt; the sidebar's avatar/username and each deck's
        contents are refreshed in place instead."""
        if self.app.username:  # nothing to (re)read if no one's logged in
            self.app.load(self.app.username)
        self.sidebar.refresh_profile(self.app)

        self._replace_screen("home_screen", self._new_home_screen())
        self._replace_screen("decks_screen", self._new_decks_screen())
        self._replace_screen("collection_screen", self._new_collection_screen())

        # Not rebuilt (that would lose a deck in progress) — just re-read
        self.deck_maker_screen.reload_collection()

        self._lazy_load_decks()  # re-fetch each deck's contents in the background

    def _replace_screen(self, attr_name: str, new_widget: QWidget):
        """Swaps the screen stored at self.<attr_name> for `new_widget` in
        both the stack and the instance attribute, preserving the stack's
        page order and which page is currently visible. attr_name: e.g.
        "home_screen". new_widget: the freshly-built replacement screen."""
        old_widget = getattr(self, attr_name)
        was_current = self.stack.currentWidget() is old_widget
        index = self.stack.indexOf(old_widget)

        self.stack.insertWidget(index, new_widget)
        self.stack.removeWidget(old_widget)
        old_widget.deleteLater()
        if was_current:
            self.stack.setCurrentWidget(new_widget)

        setattr(self, attr_name, new_widget)

    def _lazy_load_decks(self):
        """Kicks off loading every deck's contents in the background, so
        startup (or a post-refresh/login/clear-cache rebuild) doesn't
        block the UI. Scheduled via QTimer.singleShot after __init__ and
        called again directly from _rebuild_data_screens()."""
        run_in_background(
            self._load_all_deck_contents,
            self._bg_tasks,
            on_finished=self._on_decks_loaded,
        )

    def _load_all_deck_contents(self):
        """Background-task body: loads every deck that isn't already
        loaded, cache-only first, falling back to a forced fetch if the
        cache is missing (e.g. cleared) or in an older format (see
        Deck.outdated). One deck failing to fetch doesn't stop the rest."""
        for deck in self.app.decks:
            if not deck.cards:
                deck.load()
            if not deck.cards or deck.outdated:  # missing/outdated cache — fetch it
                try:
                    deck.load(force=True)
                except Exception:
                    pass  # one deck failing to fetch shouldn't block the rest

    def _on_decks_loaded(self, _result):
        """Background-task callback: refreshes the Decks screen's grid
        now that deck contents (format, in particular) are available.
        _result is unused (_load_all_deck_contents returns None)."""
        # Trigger the decks screen to refresh now that data is available
        self.decks_screen.rebuild_grid()
        self.deck_maker_screen.refresh_usage()  # "used in another deck" marks need deck contents
        self._prefetch_images()

    def _prefetch_images(self):
        """Starts downloading every deck and collection image that isn't
        cached yet, in the background (see image_prefetch.py) — decks
        first, since they're fewer. Runs once deck contents are loaded:
        after startup and after every refresh/login/cache-clear rebuild
        (each restart cancels the previous run)."""
        items = {}  # cache_name -> url (dict dedupes, keeps order)
        for deck in self.app.decks:
            if deck.commanders and deck.commanders[0].get("image_url"):
                items.setdefault(scryfall.card_image_cache_name(deck.commanders[0]), deck.commanders[0]["image_url"])
            for card in deck.cards:
                if card.get("image_url"):
                    items.setdefault(scryfall.card_image_cache_name(card), card["image_url"])
        for entry in self.app.collection.cards:
            url = scryfall.image_url(entry["card"].get("scryfall_id", ""))
            if url:
                items.setdefault(scryfall.card_image_cache_name(entry["card"]), url)
        self._image_prefetcher.start((url, name) for name, url in items.items())
