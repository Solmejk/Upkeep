"""TokenSheetPreview: the Token Printer's page preview — the A4 pages the
document will have, drawn to scale with the same layout as token_print.py
(images turned 90° clockwise, two per row, centred, square corners, crop
marks). Painted from the normal-size card images (loaded through
ImageLoader, so it never blocks), not the full-size print images.
"""

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

import scryfall
import token_print as tp
from ui.image_loader import ImageLoader
from ui import theme

MIN_PAGE_PX_W, MAX_PAGE_PX_W = 300, 640  # page width range — it grows with the window (set_page_width)
PAGE_GAP = 34             # between pages (room for the "Page n of m" label)
PAPER = QColor("#f4f4f4")
PLACEHOLDER = QColor("#d0d0d0")
TEXT_MUTED = QColor(theme.MUTED)
MARK = QColor("black")  # crop marks
NORMAL_CORNER_PX = 22   # corner radius of Scryfall's normal images (488 px wide)


class TokenSheetPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots = []  # one token per printed copy, in document order
        self._pixmaps = {}  # cache name -> rotated QPixmap
        self._requested = set()
        self.set_page_width(MIN_PAGE_PX_W)

    def set_page_width(self, px: int):
        """Scales the pages to `px` wide (clamped to the allowed range)."""
        px = max(MIN_PAGE_PX_W, min(MAX_PAGE_PX_W, int(px)))
        self._page_px_w = px
        self._scale = px / tp.PAGE_W_MM  # px per mm
        self._page_px_h = round(tp.PAGE_H_MM * self._scale)
        self.setFixedWidth(px)
        self._resize_for_pages()
        self.update()

    def set_items(self, tokens_with_counts: list):
        """[(token, copies)] — repaints the pages for these counts."""
        self._slots = [token for token, n in tokens_with_counts for _ in range(max(n, 0))]
        for token in {scryfall.card_image_cache_name(t): t for t in self._slots}.values():
            self._request_image(token)
        self._resize_for_pages()
        self.update()

    def page_count(self) -> int:
        return -(-len(self._slots) // tp.PER_PAGE)  # ceil

    def _resize_for_pages(self):
        pages = max(self.page_count(), 1)
        self.setFixedHeight(pages * (self._page_px_h + PAGE_GAP))

    # ---------------------------------------------------------- images
    def _request_image(self, token: dict):
        name = scryfall.card_image_cache_name(token)
        if name in self._requested:
            return
        self._requested.add(name)
        w, h = 488, 680  # the normal image's own size — sharp at any preview size
        ImageLoader.instance().submit(name, token["image_url"], name, w, h, 0, self._on_image_ready)

    def _on_image_ready(self, name, image):
        pixmap = QPixmap.fromImage(_square_corners(image)).transformed(QTransform().rotate(90),
                                                                        Qt.SmoothTransformation)
        self._pixmaps[name] = pixmap
        self.update()

    # -------------------------------------------------------- painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self._scale
        pages = self.page_count()

        if pages == 0:
            self._paint_page(painter, 0)
            painter.setPen(TEXT_MUTED)
            painter.drawText(QRectF(0, 0, self._page_px_w, self._page_px_h), Qt.AlignCenter,
                             "Nothing to print")
            painter.end()
            return

        # the grid's / crop marks' origin on the page: the printable area's
        # corner (the margins) plus the grid's offset in it — as token_print
        ox, oy = tp.MARGIN_MM + tp.GRID_X_MM, tp.MARGIN_MM + tp.GRID_Y_MM
        for page in range(pages):
            top = self._paint_page(painter, page)
            on_page = min(tp.PER_PAGE, len(self._slots) - page * tp.PER_PAGE)
            for slot in range(on_page):
                i = page * tp.PER_PAGE + slot
                row, col = divmod(slot, tp.PER_ROW)
                rect = QRectF((ox + col * tp.IMAGE_WIDTH_MM) * s,
                              top + (oy + row * tp.IMAGE_HEIGHT_MM) * s,
                              tp.IMAGE_WIDTH_MM * s, tp.IMAGE_HEIGHT_MM * s)
                token = self._slots[i]
                pixmap = self._pixmaps.get(scryfall.card_image_cache_name(token))
                if pixmap is not None:
                    painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
                else:
                    painter.fillRect(rect, PLACEHOLDER)
                    painter.setPen(QColor(theme.FAINT))
                    painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, token["name"])

            # crop marks (token_print.crop_marks is relative to the printable area)
            painter.setPen(QPen(MARK, max(1.0, tp.MARK_WIDTH_MM * s)))
            for x1, y1, x2, y2 in tp.crop_marks(on_page):
                painter.drawLine(QPointF((tp.MARGIN_MM + x1) * s, top + (tp.MARGIN_MM + y1) * s),
                                 QPointF((tp.MARGIN_MM + x2) * s, top + (tp.MARGIN_MM + y2) * s))

            painter.setPen(TEXT_MUTED)
            painter.drawText(QRectF(0, top + self._page_px_h + 4, self._page_px_w, 20),
                             Qt.AlignHCenter | Qt.AlignTop, f"Page {page + 1} of {pages}")
        painter.end()

    def _paint_page(self, painter, page: int) -> float:
        """Draws one blank sheet; returns its top y."""
        top = page * (self._page_px_h + PAGE_GAP)
        painter.setPen(Qt.NoPen)
        painter.setBrush(PAPER)
        painter.drawRect(QRectF(0, top, self._page_px_w, self._page_px_h))
        return top


def _square_corners(image: QImage) -> QImage:
    """The preview's version of token_print.square_corners, for Scryfall's
    normal images (their rounded corners are filled with white): each
    corner square painted in the card's colour next to it, then the card
    drawn on top clipped to its rounded shape."""
    w, h = image.width(), image.height()
    if w < 4 * NORMAL_CORNER_PX or h < 4 * NORMAL_CORNER_PX:
        return image
    r = NORMAL_CORNER_PX * w / 488
    out = QImage(w, h, QImage.Format_RGB32)
    out.fill(QColor("white"))
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    ri = round(r)
    for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        dx, dy = (1 if cx == 0 else -1), (1 if cy == 0 else -1)
        a = image.pixelColor(cx + dx * (ri + 6), cy + dy * 4)
        b = image.pixelColor(cx + dx * 4, cy + dy * (ri + 6))
        colour = QColor((a.red() + b.red()) // 2, (a.green() + b.green()) // 2, (a.blue() + b.blue()) // 2)
        size = ri + 2
        painter.fillRect(QRectF(0 if dx > 0 else w - size, 0 if dy > 0 else h - size, size, size), colour)
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(0, 0, w, h), r, r)
    painter.setClipPath(shape)
    painter.drawImage(0, 0, image)
    painter.end()
    return out
