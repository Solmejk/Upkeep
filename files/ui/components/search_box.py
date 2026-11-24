"""SearchBox: the Scryfall-syntax search field used by the Collection
and DeckDetail screens — a line edit plus a status label (result
count, or the parse error when the query is invalid). Compiles the
query (card_search.compile_query) once typing pauses and emits the
resulting predicate; the screen decides what to filter with it.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QSizePolicy

import card_search

ERROR_COLOR = "#e06c6c"


class SearchBox(QWidget):
    # predicate (entry dict -> bool), or None when the box is empty.
    # Not emitted for invalid queries — the error shows in the label and
    # the screen keeps its current results.
    search_changed = Signal(object)

    def __init__(self, placeholder: str, width: int = 340, delay_ms: int = 250,
                 status_above: bool = False, context_fn=None):
        """placeholder: hint text in the empty box. width: the line
        edit's fixed width. delay_ms: pause after the last keystroke
        before the query is compiled and applied. status_above: put the
        status label (result count / error) above the field, right-
        aligned, instead of to its left. context_fn: optional callable
        returning the card_search context (e.g. {"is_used": ...}), called
        on every search so it reflects the current decks."""
        super().__init__()
        self._context_fn = context_fn
        # never wider than its contents — a parent layout handing it spare
        # room would push the status text away from the field
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        layout = QVBoxLayout(self) if status_above else QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4 if status_above else 0)

        self._status = QLabel()
        self._status.setObjectName("resultCount")
        if status_above:
            # same width as the field, so the right-aligned text ends where
            # the field does; long error messages wrap instead of widening it
            self._status.setObjectName("resultCountAbove")  # no right padding
            self._status.setAlignment(Qt.AlignRight)
            self._status.setFixedWidth(width)
            self._status.setWordWrap(True)
            # the whole box is exactly the field's width — otherwise a parent
            # layout can hand it spare room, leaving a gap right of the field
            self.setFixedWidth(width)
        layout.addWidget(self._status)

        self._input = QLineEdit()
        self._input.setObjectName("searchInput")
        self._input.setPlaceholderText(placeholder)
        self._input.setToolTip(
            "Scryfall-style search, e.g.  t:creature c:g mv<=3\n"
            "Full guide: Settings → Search syntax"
        )
        self._input.setFixedWidth(width)
        self._input.textChanged.connect(lambda _: self._timer.start())
        layout.addWidget(self._input)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._apply)

    def text(self) -> str:
        return self._input.text()

    def set_result_text(self, text: str):
        """Shows `text` (e.g. "12 results") in the status label."""
        self._status.setStyleSheet("")
        self._status.setText(text)

    def clear(self):
        """Empties the box without emitting search_changed (for screens
        that reset their own content anyway, e.g. opening another deck)."""
        self._input.blockSignals(True)
        self._input.clear()
        self._input.blockSignals(False)
        self._timer.stop()
        self.set_result_text("")

    def _apply(self):
        """Timer slot: compiles the current text and emits the predicate,
        or shows the parse error."""
        query = self._input.text().strip()
        if not query:
            self.set_result_text("")
            self.search_changed.emit(None)
            return
        try:
            context = self._context_fn() if self._context_fn else None
            predicate = card_search.compile_query(query, context)
        except card_search.SearchError as e:
            self._status.setStyleSheet(f"color: {ERROR_COLOR};")
            self._status.setText(str(e))
            return
        self.search_changed.emit(predicate)
