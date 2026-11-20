"""Shared building blocks for the settings-style pages:

    SectionCard  — a titled card (title, description, optional content,
                   right-aligned buttons), as on Settings and Other Apps.
    back_button  — the "← Back" button at the top of every sub-page.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

SECTION_WIDTH = 480


def back_button(on_click) -> QPushButton:
    """The "← Back" button sub-pages start with."""
    button = QPushButton("← Back")
    button.setObjectName("backButton")
    button.clicked.connect(on_click)
    return button


class SectionCard(QFrame):
    """A titled card: title, a description, then (optionally) your own
    widgets in `self.body`, then right-aligned buttons (add_button). Fixed
    height, so a short window scrolls the page instead of squashing it."""

    def __init__(self, title: str, description: str = "", width: int = SECTION_WIDTH):
        super().__init__()
        self.setObjectName("settingsSection")
        self.setMaximumWidth(width)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        self.body.addWidget(heading)

        if description:
            text = QLabel(description)
            text.setObjectName("settingsDescription")
            text.setWordWrap(True)
            self.body.addWidget(text)

        self._buttons = None  # the button row, made on first add_button

    def add_button(self, text: str, on_click, secondary: bool = False) -> QPushButton:
        """A button in the card's bottom-right row (secondary: the outlined
        style, next to a main action). Returns it."""
        if self._buttons is None:
            self._buttons = QHBoxLayout()
            self._buttons.addStretch()
            self.body.addLayout(self._buttons)
        button = QPushButton(text)
        if secondary:
            button.setObjectName("backButton")
        button.clicked.connect(on_click)
        self._buttons.addWidget(button)
        return button
