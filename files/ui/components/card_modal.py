"""CardModal: the full-size card popout used across the app (Collection,
Decks/DeckDetail, and Availability screens all open the same instance via
MainWindow.card_modal). Shows the card art plus, when the clicked card
carries that data (only the Availability screen's results do), how many
of each printing you own and which of your decks use it — and the
printing's price history (models.price_history) when there is one.
"""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton

import scryfall
from image_cache import get_image_path
from languages import DEFAULT_LANGUAGE, deck_card_language, language_name
from ui.components.image_tile import round_pixmap
from ui.components.overlay_modal import OverlayModal
from ui.components.value_chart import ValueChart
from models import price_history, token_printings
from paths import ASSETS_DIR
from ui.icon_utils import tinted_icon


CARD_IMG_WIDTH = 360
CARD_IMG_HEIGHT = 504  # 5:7 ratio, scaled up
CARD_IMG_RADIUS = 18
FLIP_BUTTON_SIZE = 34
FLIP_BUTTON_STYLE = """
QToolButton {
    background-color: rgba(26, 26, 26, 200);
    border: 1px solid rgba(232, 232, 232, 70);
    border-radius: 17px;
    padding: 0;
}
QToolButton:hover {
    background-color: rgba(26, 26, 26, 240);
    border: 1px solid #e8a838;
}
"""

# Width stays constant; height instead adapts per card between these two
# bounds — small by default (a card with little/no owned/used-in info
# doesn't need a tall box with lots of empty space below it), growing only
# as far as actually needed, up to the max. Independent of the window
# size either way — never grows to fill a fullscreen window. Content that
# still doesn't fit at the max scrolls as one unit instead.
MODAL_CONTENT_WIDTH = CARD_IMG_WIDTH + 60
MODAL_MIN_HEIGHT = 650
MODAL_MAX_HEIGHT = 850


class CardModal(OverlayModal):
    """Popout showing one card at large size. Call show_card(card) to
    populate and display it. See OverlayModal for dismissal/resize
    behavior (outside-click, Esc, close button)."""

    token_printing_changed = Signal()  # a token's default printing was set / removed

    def __init__(self, parent=None):
        """Builds the (initially empty/hidden) popout chrome — image slot,
        name/meta labels, a scrollable owned/used-in info area, and a
        Close button. Content is filled in later by show_card()."""
        super().__init__(parent)

        content = QWidget()
        content.setObjectName("cardModalContent")
        content.setFixedWidth(MODAL_CONTENT_WIDTH)
        content.setFixedHeight(MODAL_MIN_HEIGHT)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 30, 30, 16)
        content_layout.setSpacing(12)

        # Everything above Close scrolls together as one unit — image, name,
        # meta, owned, used-in — with static spacing between them. Only
        # kicks in if a card has enough owned-printings/used-in text to not
        # fit the fixed popout height.
        self._scroll = QScrollArea()
        self._scroll.setObjectName("cardModalScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # QSS on the QScrollArea itself doesn't reach its viewport (a
        # separate internal widget) — without this the viewport falls back
        # to the app-wide background color, visibly darker than the card.
        self._scroll.viewport().setStyleSheet("background: transparent;")

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(self._inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(16)

        self._image_label = QLabel()
        self._image_label.setFixedSize(CARD_IMG_WIDTH, CARD_IMG_HEIGHT)
        self._image_label.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(self._image_label, alignment=Qt.AlignCenter)

        # Flip: a small round button in the image's top-right corner
        self._flip_btn = QToolButton(self._image_label)
        self._flip_btn.setObjectName("flipCardButton")
        self._flip_btn.setIcon(tinted_icon(ASSETS_DIR / "arrow.png", "#e8e8e8", size=18))
        self._flip_btn.setIconSize(QSize(18, 18))
        self._flip_btn.setFixedSize(FLIP_BUTTON_SIZE, FLIP_BUTTON_SIZE)
        self._flip_btn.setCursor(Qt.PointingHandCursor)
        self._flip_btn.setToolTip("Flip to see the back")
        self._flip_btn.move(CARD_IMG_WIDTH - FLIP_BUTTON_SIZE - 10, 10)
        self._flip_btn.clicked.connect(self._flip)
        # Its own style: the inner panel's selector-less "background:
        # transparent" would otherwise cascade onto it and drop the dark
        # circle (an ancestor's widget style beats the app stylesheet).
        self._flip_btn.setStyleSheet(FLIP_BUTTON_STYLE)
        self._card = None
        self._flipped = False

        self._name_label = QLabel()
        self._name_label.setObjectName("cardModalName")
        self._name_label.setAlignment(Qt.AlignCenter)
        self._name_label.setWordWrap(True)
        inner_layout.addWidget(self._name_label)

        self._meta_label = QLabel()
        self._meta_label.setObjectName("cardModalMeta")
        self._meta_label.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(self._meta_label)

        self._language_label = QLabel()
        self._language_label.setObjectName("cardModalMeta")
        self._language_label.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(self._language_label)

        # Price over time for this printing (+ finish) — collection cards
        # only (others have no history); see models.price_history
        self._price_chart = ValueChart(
            title="Price history",
            empty_text="No price history yet — it starts with the next collection refresh.")
        self._price_chart.setFixedSize(CARD_IMG_WIDTH, 170)
        inner_layout.addWidget(self._price_chart, alignment=Qt.AlignCenter)

        # Deck tokens only: pick which printing to show for this token
        self._token_printing_btn = QPushButton("Set default printing…")
        self._token_printing_btn.setObjectName("backButton")  # yellow text, like Close
        self._token_printing_btn.setToolTip("Choose the art shown for this token in every deck")
        self._token_printing_btn.clicked.connect(self._choose_token_printing)
        inner_layout.addWidget(self._token_printing_btn, alignment=Qt.AlignCenter)

        # Only populated (and shown) for cards from the availability check —
        # Collection/DeckDetail cards don't carry this data.
        self._owned_label = QLabel()
        self._owned_label.setObjectName("cardModalMeta")
        self._owned_label.setAlignment(Qt.AlignCenter)
        self._owned_label.setWordWrap(True)
        inner_layout.addWidget(self._owned_label)

        self._used_in_label = QLabel()
        self._used_in_label.setObjectName("cardModalMeta")
        self._used_in_label.setAlignment(Qt.AlignCenter)
        self._used_in_label.setWordWrap(True)
        inner_layout.addWidget(self._used_in_label)

        self._scroll.setWidget(self._inner)
        content_layout.addWidget(self._scroll, 1)

        self._close_btn = QPushButton("Close")
        self._close_btn.setObjectName("backButton")
        self._close_btn.clicked.connect(self._dismiss)
        content_layout.addWidget(self._close_btn, alignment=Qt.AlignCenter)

        self._init_overlay(content)

    def show_card(self, card: dict):
        """Populates the popout for `card` and displays it.

        card: a flat dict with at least name/set/cn/price/image_url — the
        shape produced by Collection/Deck/Availability screens for their
        clicked-card payloads. If it also carries owned_printings/
        used_in_decks (only Availability results do), those sections show;
        otherwise they're hidden.
        """
        # Load the image (we have it cached already) — always the front first
        self._card = card
        self._flipped = False
        self._flip_btn.setToolTip("Flip to see the back")
        self._set_image(get_image_path(card.get("image_url", ""), scryfall.card_image_cache_name(card)))

        # Details
        self._name_label.setText(card["name"])
        set_code = card.get("set", "").upper()
        cn = card.get("cn", "")
        price = card.get("price", 0)
        self._meta_label.setText(f"{set_code} · #{cn} · €{price:.2f}")
        # the copy's language if the payload says (collection / Deck Maker
        # cards), else the printing's — Moxfield decks don't record it
        languages = card.get("languages")
        if languages and len(languages) > 1:
            breakdown = ", ".join(f"{n}x {language_name(code)}" for code, n in languages.items())
            self._language_label.setText(f"Languages: {breakdown}")
        else:
            self._language_label.setText(f"Language: {language_name(deck_card_language(card))}")

        self._token_printing_btn.setVisible(bool(card.get("uid")))  # deck tokens carry a uid

        foil = bool(card.get("isFoil")) or str(card.get("finish", "")).lower() in ("foil", "etched")
        history = price_history.series(card["scryfall_id"], foil) if card.get("scryfall_id") else []
        self._price_chart.setHistory(history)
        self._price_chart.setVisible(bool(history))

        owned_printings = card.get("owned_printings")
        if owned_printings:
            total_owned = sum(p["quantity"] for p in owned_printings)
            lines = [f"Owned {total_owned}"]
            lines += [_owned_line(p) for p in owned_printings]
            self._owned_label.setText("\n".join(lines))
            self._owned_label.show()
        else:
            self._owned_label.hide()

        used_in_decks = card.get("used_in_decks")
        if used_in_decks:
            lines = ["Used in:"]
            lines += [_used_line(d) for d in used_in_decks]
            self._used_in_label.setText("\n".join(lines))
            self._used_in_label.show()
        elif card.get("made_by"):  # a deck's token: which of its cards create it
            self._used_in_label.setText("\n".join(["Made by:"] + card["made_by"]))
            self._used_in_label.show()
        else:
            self._used_in_label.hide()

        self._resize_to_fit()
        self._show_overlay()

    def _choose_token_printing(self):
        """Opens the printing picker for the shown token; after a change,
        shows the token again with its new printing and tells the deck
        screen to refresh."""
        from ui.components.token_printing_dialog import TokenPrintingDialog  # avoids an import cycle
        if TokenPrintingDialog(self.window(), self._card).exec():
            self.show_card(token_printings.apply(self._card))
            self.token_printing_changed.emit()

    def _set_image(self, path):
        if not path:
            return
        pixmap = QPixmap(str(path)).scaled(
            CARD_IMG_WIDTH, CARD_IMG_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(round_pixmap(pixmap, CARD_IMG_RADIUS))

    def _flip(self):
        """Flip button: front <-> back."""
        card = self._card
        if card is None:
            return
        self._flipped = not self._flipped
        self._flip_btn.setToolTip("Flip to see the front" if self._flipped else "Flip to see the back")
        if self._flipped:
            self._set_image(_back_image_path(card))
        else:
            self._set_image(get_image_path(card.get("image_url", ""), scryfall.card_image_cache_name(card)))

    def _resize_to_fit(self):
        """Sets the popout's height to fit this card's actual content,
        clamped between MODAL_MIN_HEIGHT and MODAL_MAX_HEIGHT — small by
        default, growing only as far as needed. Content beyond the max
        still scrolls (see the scroll area in __init__)."""
        self._inner.adjustSize()
        content_layout = self._content.layout()
        margins = content_layout.contentsMargins()
        chrome = (
            margins.top() + margins.bottom()
            + content_layout.spacing()
            + self._close_btn.sizeHint().height()
        )
        desired = self._inner.sizeHint().height() + chrome
        height = max(MODAL_MIN_HEIGHT, min(MODAL_MAX_HEIGHT, desired))
        self._content.setFixedHeight(height)


def _used_line(use: dict) -> str:
    """One "Used in" line: "Deck (1x)", or "Deck (1x English)" when the
    language of the copy is known (Collection cards)."""
    if use.get("language"):
        return f"{use['deck_name']} ({use['quantity']}x {language_name(use['language'])})"
    return f"{use['deck_name']} ({use['quantity']}x)"


def _back_image_path(card: dict):
    """A card's back: its custom back image (Settings → Custom card
    images), else a double-faced card's back face, else the Magic card back.
    Single-faced cards have no back-face image on Scryfall, so that lookup
    just fails and falls through to the card back."""
    back_name = scryfall.back_cache_name(card)
    front_url = card.get("image_url", "")
    back_url = front_url.replace("/normal/front/", "/normal/back/") if "/normal/front/" in front_url else ""
    if back_name in _NO_BACK_FACE:
        back_url = ""  # known single-faced: don't ask Scryfall again (still allows a custom back)
    path = get_image_path(back_url, back_name)  # custom back, or the real back face
    if path is None and back_url:
        _NO_BACK_FACE.add(back_name)
    return path or get_image_path(scryfall.MAGIC_BACK_URL, scryfall.MAGIC_BACK_CACHE_NAME)


_NO_BACK_FACE = set()  # back cache names Scryfall had no back-face image for (this session)


def _owned_line(printing: dict) -> str:
    """One "Owned" line: "2x CMM", plus the language for non-English
    copies ("1x CMM · Japanese")."""
    line = f"{printing['quantity']}x {printing['set'].upper()}"
    language = printing.get("language", DEFAULT_LANGUAGE)
    if language != DEFAULT_LANGUAGE:
        line += f" · {language_name(language)}"
    return line
