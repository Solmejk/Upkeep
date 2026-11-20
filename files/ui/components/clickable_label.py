"""ClickableLabel: a QLabel that acts as a button — emits `clicked` on a
left click and keeps that click (the widget underneath, e.g. a game card
that opens its editor, doesn't also get it). Right clicks pass through,
so context menus on the parent still work. Shows the pointing-hand
cursor. Used for card images and captions, the sidebar avatar, player /
deck names, the Home Elo and the Availability bookmark.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit()
            return
        super().mousePressEvent(event)
