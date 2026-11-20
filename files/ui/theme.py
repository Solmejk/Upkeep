"""The app's colors for Python-drawn UI (charts, painted widgets, inline
rich text) — the same palette as style.qss, which styles everything else.
Change a color here (and in style.qss) rather than in the widgets.
"""

from models.game_tracker import ELO_START  # the Elo every player / deck starts at

ACCENT = "#e8a838"      # orange: titles, buttons, highlights, chart lines
TEXT = "#e8e8e8"        # main text
MUTED = "#888888"       # secondary text, captions, axis labels
FAINT = "#555555"       # very quiet lines / placeholders (crosshair, missing images)
DIMMED = "#666666"      # inactive / switched-off text

PAGE_BG = "#1a1a1a"     # window background
SURFACE = "#222222"     # cards, panels, tooltips
CONTROL_BG = "#2a2a2a"  # inputs, placeholders
BORDER = "#2d2d2d"      # borders, grid lines

WIN = "#4caf50"         # good / free / received / rising / won
WARN = "#e8a838"        # used elsewhere (= ACCENT)
LOSS = "#d9534f"        # bad / missing / falling / lost


def elo_color(elo: float) -> str:
    """An Elo rating's color: green above the 1500 start, red below."""
    if elo >= ELO_START + 0.5:
        return WIN
    if elo <= ELO_START - 0.5:
        return LOSS
    return TEXT
