"""The " Sort" dropdown button shared by the Availability screen and the
Deck Maker: a QToolButton with the sort icon that pops up an exclusive
(radio-button-like) menu of sort modes, the current one checked.
"""

from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QToolButton, QMenu

from paths import ASSETS_DIR
from ui.icon_utils import tinted_icon


def build_sort_button(modes: dict, current: str, on_changed) -> QToolButton:
    """modes: mode -> menu label, in menu order. current: the initially
    checked mode. on_changed(mode): called when another mode is picked."""
    button = QToolButton()
    button.setText(" Sort")
    button.setIcon(tinted_icon(ASSETS_DIR / "sort.png", "#e8e8e8", size=14))
    button.setIconSize(QSize(14, 14))
    button.setPopupMode(QToolButton.InstantPopup)

    menu = QMenu(button)
    group = QActionGroup(menu)
    group.setExclusive(True)
    for mode, label in modes.items():
        action = QAction(label, menu)
        action.setCheckable(True)
        action.setChecked(mode == current)
        action.triggered.connect(lambda checked, m=mode: on_changed(m))
        group.addAction(action)
        menu.addAction(action)

    button.setMenu(menu)
    return button
