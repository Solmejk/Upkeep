"""TokenSheetPreview: the Token Printer's page preview — the A4 pages the
document will have, drawn to scale with the same layout as token_print.py
(images turned 90° clockwise, two per row, 10 mm margins). Painted from
the normal-size card images (loaded through ImageLoader, so it never
blocks), not the full-size print images.
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QTransform, QPixmap
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
        pixmap = QPixmap.fromImage(image).transformed(QTransform().rotate(90), Qt.SmoothTransformation)
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

        for page in range(pages):
            top = self._paint_page(painter, page)
            for slot in range(tp.PER_PAGE):
                i = page * tp.PER_PAGE + slot
                if i >= len(self._slots):
                    break
                row, col = divmod(slot, tp.PER_ROW)
                rect = QRectF((tp.MARGIN_MM + col * tp.IMAGE_WIDTH_MM) * s,
                              top + (tp.MARGIN_MM + row * tp.IMAGE_HEIGHT_MM) * s,
                              tp.IMAGE_WIDTH_MM * s, tp.IMAGE_HEIGHT_MM * s)
                token = self._slots[i]
                pixmap = self._pixmaps.get(scryfall.card_image_cache_name(token))
                if pixmap is not None:
                    painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
                else:
                    painter.fillRect(rect, PLACEHOLDER)
                    painter.setPen(QColor(theme.FAINT))
                    painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, token["name"])

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
