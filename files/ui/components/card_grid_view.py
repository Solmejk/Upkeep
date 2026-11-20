"""CardGridView: the Collection screen's card grid. Unlike the tile-based
grids elsewhere (Decks, DeckDetail, Availability — see ImageTile), this
one is a virtualized QListView + custom delegate, since a full collection
can be thousands of cards and building a real widget per card would be
far too slow/memory-heavy.
"""

from PySide6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QRect, QRectF, Signal, QPoint,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPen, QImage, QFontMetrics,
)
from PySide6.QtWidgets import (
    QListView, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
)

import card_sort
import scryfall
from languages import entry_language
from ui.image_loader import ImageLoader
from ui.components.image_tile import make_placeholder, paint_tint_overlay
from ui import theme


CELL_WIDTH = 140  # default; CardGridView(cell_width=...) overrides it
IMAGE_RATIO = 196 / 140  # image height / width (card proportions)
CAPTION_SPACE = 40  # below the image, per cell
IMAGE_RADIUS = 12
CAPTION_HEIGHT = 36
SCROLL_STEP = 40  # pixels per scroll step; a mouse wheel tick is 3 steps

FOIL_COLOR = QColor("#9b59b6")  # purple, gradient start
FOIL_COLOR2 = QColor("#f1c40f")  # yellow, gradient end
FOIL_ALPHA = 50  # Foil transparency
STATUS_ALPHA = 90  # status tint (tint_fn) — same strength as ImageTile's status_color


class CollectionModel(QAbstractListModel):
    """Wraps a list of card entries with optional filtering (a search
    predicate — see card_search / ui.components.search_box)."""

    def __init__(self, cards: list, parent=None):
        """cards: raw Moxfield collection entries (list of {"quantity":
        int, "card": {...}, ...})."""
        super().__init__(parent)
        self._all_cards = cards
        self._filtered = cards

    def rowCount(self, parent=QModelIndex()):
        """Qt model API: number of rows currently shown (post-filter)."""
        if parent.isValid():
            return 0
        return len(self._filtered)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        """Qt model API: Qt.UserRole returns the full entry dict (what
        the delegate paints from); Qt.DisplayRole returns just the card
        name (used for accessibility/sorting, not painted directly)."""
        if not index.isValid() or index.row() >= len(self._filtered):
            return None
        entry = self._filtered[index.row()]
        if role == Qt.UserRole:
            # Return the full entry; the delegate / consumers decode it
            return entry
        if role == Qt.DisplayRole:
            return entry["card"]["name"]
        return None

    def setFilter(self, predicate):
        """Narrows the visible rows to entries for which predicate(entry)
        is true; None shows everything."""
        self.beginResetModel()
        if predicate is None:
            self._filtered = self._all_cards
        else:
            self._filtered = [e for e in self._all_cards if predicate(e)]
        self.endResetModel()


class CardThumbnailDelegate(QStyledItemDelegate):
    """Paints a card cell: rounded image + caption. Loads images via ImageLoader."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view = None
        self.tint_fn = None  # entry -> QColor | None: status wash + hover border color
        self.set_cell_width(CELL_WIDTH)

    def set_cell_width(self, width: int):
        """Sets the cell (and image) width — height follows from card
        proportions. Drops already-loaded images, since they were scaled
        for the old size."""
        self.cell_width = width
        self.image_height = round(width * IMAGE_RATIO)
        self.cell_height = self.image_height + CAPTION_SPACE
        self._pixmap_cache = {}  # token -> QPixmap
        self._requested = set()  # tokens already requested
        self._placeholder = make_placeholder(width, self.image_height, IMAGE_RADIUS)

    def attach_view(self, view: QListView):
        """Used so the delegate can tell the view to repaint a specific row."""
        self._view = view

    def sizeHint(self, option, index):
        return QSize(self.cell_width, self.cell_height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """Qt delegate API: paints one cell — the (possibly still-loading
        placeholder) image, a foil tint if applicable, a hover border,
        and the elided card-name caption. Also lazily kicks off an
        ImageLoader fetch the first time a given card's image is needed."""
        entry = index.data(Qt.UserRole)
        if entry is None:
            return
        
        token = scryfall.card_key(entry["card"])
        rect = option.rect
        
        # Compute paint positions
        img_x = rect.x()
        img_y = rect.y()
        caption_y = img_y + self.image_height + 4
        
        # Image
        pixmap = self._pixmap_cache.get(token, self._placeholder)
        # Center horizontally if narrower than cell
        x = img_x + (self.cell_width - pixmap.width()) // 2
        painter.drawPixmap(x, img_y, pixmap)

        # Foil tint — a very slight translucent purple-to-yellow fade, rounded to match the image
        if entry.get("isFoil"):
            color = QColor(FOIL_COLOR)
            color.setAlpha(FOIL_ALPHA)
            color2 = QColor(FOIL_COLOR2)
            color2.setAlpha(FOIL_ALPHA)
            paint_tint_overlay(
                painter, QRectF(x, img_y, pixmap.width(), pixmap.height()), IMAGE_RADIUS, color, color2,
            )

        # Status tint (e.g. the Deck Maker's "used in another deck"), same
        # wash as the Availability screen's tiles
        status_color = self.tint_fn(entry) if self.tint_fn else None
        if status_color is not None:
            wash = QColor(status_color)
            wash.setAlpha(STATUS_ALPHA)
            paint_tint_overlay(painter, QRectF(x, img_y, pixmap.width(), pixmap.height()), IMAGE_RADIUS, wash)

        # Hover border around image (in the status color, if tinted)
        if option.state & QStyle.State_MouseOver:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(status_color) if status_color is not None else QColor(theme.ACCENT))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(
                QRectF(x, img_y, pixmap.width(), pixmap.height()),
                IMAGE_RADIUS + 2, IMAGE_RADIUS + 2,
            )
            painter.restore()
        
        # Caption
        painter.save()
        painter.setPen(QColor(theme.TEXT))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        
        quantity = entry["quantity"]
        qty_prefix = f"{quantity}x " if quantity > 1 else ""
        foil_prefix = "F  " if entry.get("isFoil") else ""
        caption = f"{qty_prefix}{foil_prefix}{entry['card']['name']}"
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(caption, Qt.ElideRight, self.cell_width)
        caption_rect = QRect(img_x, caption_y, self.cell_width, CAPTION_HEIGHT)

        if foil_prefix and elided.startswith(qty_prefix + foil_prefix):
            rest = elided[len(qty_prefix) + len(foil_prefix):]
            qty_width = metrics.horizontalAdvance(qty_prefix)
            foil_width = metrics.horizontalAdvance(foil_prefix)
            rest_width = metrics.horizontalAdvance(rest)
            x_cursor = img_x + (self.cell_width - qty_width - foil_width - rest_width) // 2

            if qty_prefix:
                painter.drawText(QRect(x_cursor, caption_y, qty_width, CAPTION_HEIGHT), Qt.AlignTop | Qt.AlignLeft, qty_prefix)
                x_cursor += qty_width
            painter.setPen(QColor("#ffd700"))
            painter.drawText(QRect(x_cursor, caption_y, foil_width, CAPTION_HEIGHT), Qt.AlignTop | Qt.AlignLeft, foil_prefix)
            x_cursor += foil_width
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(QRect(x_cursor, caption_y, rest_width, CAPTION_HEIGHT), Qt.AlignTop | Qt.AlignLeft, rest)
        else:
            painter.drawText(caption_rect, Qt.AlignTop | Qt.AlignHCenter, elided)
        painter.restore()
        
        # Trigger an image load if we haven't yet
        if token not in self._pixmap_cache and token not in self._requested:
            url = scryfall.image_url(entry["card"].get("scryfall_id", ""))
            if url:
                self._requested.add(token)
                ImageLoader.instance().submit(
                    token=(token, self.cell_width),
                    url=url,
                    cache_name=scryfall.card_image_cache_name(entry["card"]),
                    width=self.cell_width,
                    height=self.image_height,
                    radius=IMAGE_RADIUS,
                    on_ready=self._on_image_ready,
                    on_failed=self._on_image_failed,
                )

    def _on_image_ready(self, packed_token, image: QImage):
        """ImageLoader callback (main thread): caches the decoded image
        and repaints the visible cells. Not just "the row it was
        requested for" — a search may have changed which row (if any)
        shows this card since, and repainting the viewport is cheap
        (only on-screen cells are painted). packed_token: (card token,
        cell width it was requested at) — results for an old width
        (the grid was resized meanwhile) are dropped."""
        token, width = packed_token
        if width != self.cell_width:
            return
        self._pixmap_cache[token] = QPixmap.fromImage(image)
        if self._view is not None:
            self._view.viewport().update()

    def _on_image_failed(self, packed_token):
        """ImageLoader callback (main thread): forgets the request so the
        next paint of this card retries it."""
        token, width = packed_token
        if width == self.cell_width:
            self._requested.discard(token)


class CardGridView(QListView):
    """Virtualized icon-grid view backed by a CollectionModel."""
    
    card_clicked = Signal(dict)  # emitted with a flat card payload dict on click
    entry_clicked = Signal(dict)  # emitted with the raw collection entry on click
    entry_menu_requested = Signal(dict, QPoint)  # right-click: raw entry + global position

    def __init__(self, parent=None, cell_width: int = CELL_WIDTH, tint_fn=None):
        """cell_width: width of each card cell in pixels (height follows
        from card proportions). tint_fn: optional entry -> QColor | None,
        a translucent status wash over that card's image."""
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setSelectionMode(QListView.NoSelection)
        self.setMouseTracking(True)  # needed for State_MouseOver

        self._delegate = CardThumbnailDelegate(self)
        self._delegate.set_cell_width(cell_width)
        self._delegate.tint_fn = tint_fn
        self._delegate.attach_view(self)
        self.setItemDelegate(self._delegate)

        self.clicked.connect(self._on_clicked)

        # Scroll by pixels, not by rows: per-row scrolling moves 3 whole
        # rows per wheel tick (~1300px with 280px cards).
        self.setVerticalScrollMode(QListView.ScrollPerPixel)

    def updateGeometries(self):
        """Qt resets the scroll step whenever the layout changes — re-apply
        ours, so one wheel tick (3 steps) is 3 * SCROLL_STEP pixels."""
        super().updateGeometries()
        self.verticalScrollBar().setSingleStep(SCROLL_STEP)

    def reload_images(self):
        """Drops the loaded images so they're fetched again (e.g. after an
        artist proof was added or removed)."""
        self._delegate.set_cell_width(self._delegate.cell_width)
        self.viewport().update()

    def setCardData(self, cards: list):
        """(Re)populates the grid. cards: raw Moxfield collection entries
        (see CollectionModel)."""
        model = CollectionModel(cards, self)
        self.setModel(model)

    def setFilter(self, predicate):
        """Narrows the grid to entries matching `predicate` (None shows
        everything) — see CollectionModel.setFilter."""
        model = self.model()
        if isinstance(model, CollectionModel):
            model.setFilter(predicate)

    def filtered_count(self) -> int:
        """Number of cards currently visible (post-filter)."""
        model = self.model()
        return model.rowCount() if model else 0
    
    def contextMenuEvent(self, event):
        """Right-click on a card: emits entry_menu_requested (the
        screen decides whether to show a menu)."""
        entry = self.indexAt(event.pos()).data(Qt.UserRole)
        if entry is not None:
            self.entry_menu_requested.emit(entry, event.globalPos())

    def _on_clicked(self, index: QModelIndex):
        """Qt view signal handler: reshapes the raw collection entry at
        `index` into the flat dict CardModal.show_card expects, and
        emits card_clicked."""
        entry = index.data(Qt.UserRole)
        if entry is None:
            return
        self.entry_clicked.emit(entry)
        self.card_clicked.emit(entry_payload(entry))


def entry_payload(entry: dict) -> dict:
    """A collection entry reshaped into the flat dict CardModal.show_card
    expects (also used by the Collection screen's movers)."""
    card = entry["card"]
    return {
        "name": card["name"],
        "scryfall_id": card.get("scryfall_id", ""),  # the popup's price history
        "set": card.get("set", ""),
        "cn": card.get("cn", ""),
        "quantity": entry["quantity"],
        "price": card_sort.copy_price(entry) or 0,  # foil price for foils, like the Sort menu
        "image_url": scryfall.image_url(card.get("scryfall_id", "")),
        "isFoil": entry.get("isFoil", False),
        "finish": entry.get("finish", ""),
        "language": entry_language(entry),
        "languages": entry.get("languages"),  # Collection screen: {code: copies}
    }