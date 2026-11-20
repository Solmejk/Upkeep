"""Shared pixmap helpers (round_pixmap, make_placeholder,
paint_tint_overlay) plus ImageTile: the clickable image+caption widget
used for deck tiles, deck-detail card tiles, and availability-check card
tiles. CardGridView (the Collection screen's virtualized grid) uses the
pixmap helpers directly rather than ImageTile itself, for performance.
"""

import html

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QImage, QLinearGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.image_loader import ImageLoader

# The picture's hover border (style.qss: QLabel#imageTilePicture, 2px). The
# image is drawn inside it — BORDER px smaller on every side, corners
# BORDER px less rounded — so the border's curve and the image's corners
# share a center and the hover outline hugs the card all the way round
# (drawn the full size, the image covered the border near the corners).
BORDER = 2


def round_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    """Kept for callers that still need it synchronously (e.g. card modal)."""
    size = pixmap.size()
    result = QPixmap(size)
    result.fill(Qt.transparent)
    
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    
    return result


def make_placeholder(width: int, height: int, radius: int) -> QPixmap:
    """Builds a plain dark rounded-rect pixmap shown before a card image
    has loaded (or if it fails to load)."""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#2a2a2a"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
    painter.end()

    return pixmap


def paint_tint_overlay(painter: QPainter, rect: QRectF, radius: float, color: QColor, color2: QColor | None = None):
    """Draws a translucent rounded-rect wash over `rect` onto an
    already-open `painter` — the status-color overlay in the availability
    grid and the foil overlay in the collection grid both use this.
    `color`'s alpha controls how strong the wash is. `radius` should match
    the underlying image's own corner radius so the tint doesn't spill
    past its rounded corners. If `color2` is given, paints a diagonal
    (top-left to bottom-right) gradient from `color` to `color2` instead
    of a flat wash."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    if color2 is not None:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, color)
        gradient.setColorAt(1, color2)
        painter.setBrush(gradient)
    else:
        painter.setBrush(color)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


class ClickableLabel(QLabel):
    """A QLabel that emits `clicked` on left-click — used wherever a plain
    label (image, caption, sidebar avatar/username) needs to act as a
    button."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ImageTile(QWidget):
    """
    Clickable image tile with caption. Image loads asynchronously via
    ImageLoader — call request_image_load() to kick it off.
    """
    
    clicked = Signal(object)
    
    def __init__(
        self,
        image_url: str,
        cache_name: str,
        caption: str,
        payload,
        width: int = 220,
        height: int = 310,
        radius: int = 12,
        status_color: QColor | None = None,
        caption_badge: tuple[str, str] | None = None,
    ):
        """image_url: image to fetch (request_image_load() kicks this
        off — not automatic, since callers may want to defer loading
        offscreen tiles). cache_name: on-disk cache key for the image.
        caption: text shown below the image. payload: arbitrary value
        passed back on `clicked` (typically the card/deck dict this tile
        represents). width/height/radius: tile image size and corner
        rounding. status_color: optional translucent tint + matching
        hover-border color (used by the availability screen; omit for a
        plain tile). caption_badge: optional (text, color) shown bold before
        the caption — e.g. the Decks screen's purple "M" for Moxfield
        decks, like the collection grid's yellow "F" for foils."""
        super().__init__()
        self.payload = payload
        self._image_url = image_url
        self._cache_name = cache_name
        self._width = width
        self._height = height
        self._radius = radius  # the tile's (and its hover border's) outer corner radius
        # the image itself, inside the border (see BORDER)
        self._img_w = width - 2 * BORDER
        self._img_h = height - 2 * BORDER
        self._img_radius = max(radius - BORDER, 0)
        self._loaded = False
        self._requested = False
        self._status_color = status_color

        self.setFixedWidth(width)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._image_label = ClickableLabel()
        self._image_label.setObjectName("imageTilePicture")
        self._image_label.setFixedSize(width, height)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setPixmap(self._tinted(make_placeholder(self._img_w, self._img_h, self._img_radius)))
        self._image_label.clicked.connect(lambda: self.clicked.emit(self.payload))
        # The hover border's corners follow this tile's own corner radius —
        # with the app-wide 14px, a tile rounded less (e.g. small 6-8px
        # tiles) had its image corners poke out over the border, so the
        # yellow vanished there.
        style = f"QLabel#imageTilePicture {{ border-radius: {radius}px; }}"
        if status_color is not None:
            # also overrides the hover-border color from the app-wide
            # stylesheet (QLabel#imageTilePicture:hover) for this instance
            style += f" QLabel#imageTilePicture:hover {{ border: 2px solid {status_color.name()}; }}"
        self._image_label.setStyleSheet(style)
        
        caption_label = ClickableLabel()
        if caption_badge is not None:
            badge_text, badge_color = caption_badge
            caption_label.setTextFormat(Qt.RichText)
            caption_label.setText(
                f'<span style="color:{badge_color};">{html.escape(badge_text)}</span>'
                f'&nbsp;&nbsp;{html.escape(caption)}'
            )
        else:
            caption_label.setTextFormat(Qt.PlainText)
            caption_label.setText(caption)
        caption_label.setObjectName("imageTileCaption")
        caption_label.setAlignment(Qt.AlignCenter)
        caption_label.setWordWrap(True)
        caption_label.setFixedHeight(32)  # two lines
        caption_label.clicked.connect(lambda: self.clicked.emit(self.payload))
        
        layout.addWidget(self._image_label)
        layout.addWidget(caption_label)

    def _tinted(self, pixmap: QPixmap) -> QPixmap:
        """Apply the status color as a translucent wash, matching the
        pixmap's own corner radius (it's always exactly self._radius,
        whether it's the placeholder or a loaded card image)."""
        if self._status_color is None:
            return pixmap
        result = QPixmap(pixmap)
        painter = QPainter(result)
        color = QColor(self._status_color)
        color.setAlpha(90)
        paint_tint_overlay(painter, QRectF(0, 0, result.width(), result.height()), self._img_radius, color)
        painter.end()
        return result

    def request_image_load(self):
        """Queue the image load on the background thread pool."""
        if self._loaded or self._requested or not self._image_url:
            return
        self._requested = True
        ImageLoader.instance().submit(
            token=id(self),
            url=self._image_url,
            cache_name=self._cache_name,
            width=self._img_w,
            height=self._img_h,
            radius=self._img_radius,
            fill=True,  # exactly the image box, so the hover border lines up all round
            on_ready=self._on_image_ready,
            on_failed=self._on_image_failed,
        )
    
    def _on_image_ready(self, token, image: QImage):
        """ImageLoader callback (main thread) for a successful fetch.
        token: echoed back from submit() — id(self), checked to ignore
        stray results after the tile's been reused/destroyed. image: the
        decoded, scaled, rounded QImage."""
        if token != id(self):
            return  # signal not for us
        if not self._image_label:
            return  # widget already destroyed
        # QImage -> QPixmap conversion happens here, on the main thread
        pixmap = QPixmap.fromImage(image)
        self._image_label.setPixmap(self._tinted(pixmap))
        self._loaded = True

    def _on_image_failed(self, token):
        """ImageLoader callback (main thread) for a failed fetch — resets
        _requested so a later request_image_load() call can retry."""
        if token != id(self):
            return
        self._requested = False  # allow retry later

    # Backward-compat: old call sites may still use load_image()
    def load_image(self):
        self.request_image_load()