"""StickyHeaderPage: a screen's top part (title, stats, search, ...) above
a body that scrolls on its own (a card grid, a scroll area of decks).

    Big window (maximized / fullscreen, with room left for the body): the
        top stays put and only the body scrolls — as before.
    Otherwise: the whole page scrolls. The top scrolls away first, then
        the body fills the window and scrolls on its own. The mouse wheel
        over the body moves the page until the top is gone, then the body;
        scrolling back up, the top returns once the body is at its start.

The body always stays its own scroll area (exactly the window's height
when the top can scroll away), so a virtualized grid of thousands of
cards still only draws and loads what's visible.
"""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QScrollArea, QVBoxLayout, QWidget

MIN_BODY_HEIGHT = 320  # a sticky top must leave the body at least this much (about a row of cards)


class StickyHeaderPage(QScrollArea):
    def __init__(self, top: QWidget, body: QAbstractScrollArea, parent=None):
        super().__init__(parent)
        self._top, self._body = top, body
        self._sticky = True
        self.setObjectName("decksScroll")  # transparent, borderless
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # the body's own scrollbar is the visible one

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top)
        layout.addWidget(body)
        self.setWidget(page)

        body.viewport().installEventFilter(self)  # wheel over the body: page first (see eventFilter)
        top.installEventFilter(self)              # the top changing height (wrapping, stacking)
        self._relayout_soon = QTimer(self, singleShot=True, interval=0, timeout=self._relayout)

    @property
    def sticky(self) -> bool:
        return self._sticky

    # ------------------------------------------------------------ layout
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_soon.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout_soon.start()

    def _relayout(self):
        """Sizes the body: what's left under the top when the top stays
        put, else the whole window (the top scrolls away)."""
        # never narrower than the content needs: with sideways scrolling off,
        # a too-narrow page would cut its right edge off — this keeps the
        # window from shrinking past it instead, as before this page existed
        needed = self.widget().minimumSizeHint().width()
        if self.minimumWidth() != needed:
            self.setMinimumWidth(needed)
        view_h = self.viewport().height()
        top_h = self._top.sizeHint().height()
        window = self.window()
        big = window.isMaximized() or window.isFullScreen()
        self._sticky = big and view_h - top_h >= MIN_BODY_HEIGHT
        self._body.setFixedHeight(max(MIN_BODY_HEIGHT // 2, view_h - top_h) if self._sticky else view_h)
        if self._sticky:
            self.verticalScrollBar().setValue(0)

    # ------------------------------------------------------------- wheel
    def eventFilter(self, obj, event):
        if event.type() == QEvent.LayoutRequest and obj is self._top:
            self._relayout_soon.start()  # e.g. the movers stacked: the top changed height
        elif event.type() == QEvent.Wheel and obj is self._body.viewport() and not self._sticky:
            dy = event.angleDelta().y()
            page, inner = self.verticalScrollBar(), self._body.verticalScrollBar()
            if dy < 0 and page.value() < page.maximum():         # down: the top goes first
                page.setValue(page.value() - dy)
                return True
            if dy > 0 and inner.value() == inner.minimum() and page.value() > 0:  # up, body at its start
                page.setValue(page.value() - dy)
                return True
        return False
