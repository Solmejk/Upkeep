"""Draws the app icon (files/assets/app_icon.png + app_icon.ico): a slim
orange arrow pointing right on a dark rounded tile, with slanted slices
trailing behind it so it looks like it's moving.
Run once; the results are committed, so builds don't need to run this:

    python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "files" / "assets"
ACCENT = (232, 168, 56, 255)  # the app's orange (ui/theme.py ACCENT)
DARK = (26, 26, 26, 255)      # the app's background (ui/theme.py PAGE_BG)
S = 1024  # drawn large, scaled down smoothly

MID = S // 2
TIP_X, HEAD_X = 900, 640           # the arrow's tip / where the head meets the body
HEAD_HALF, BODY_HALF = 250, 105    # half heights of the head and the body (and slices)
BODY_START = 470                   # the body's left end
SLANT = 60                         # how far the slanted cuts lean (top vs bottom)
GAP = 40                           # space between the body and each slice
SLICES = [110, 80, 50]             # slice widths, nearest the arrow first


def slanted_band(left, right):
    """A band at body height whose left and right ends lean forward."""
    top, bottom, half = MID - BODY_HALF, MID + BODY_HALF, SLANT / 2
    return [(left + half, top), (right + half, top), (right - half, bottom), (left - half, bottom)]


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=200, fill=DARK)  # the tile

# The arrow: a triangular head and a short body with a slanted back end
top, bottom, half = MID - BODY_HALF, MID + BODY_HALF, SLANT / 2
d.polygon([
    (TIP_X, MID),                      # tip
    (HEAD_X, MID + HEAD_HALF),         # head, bottom corner
    (HEAD_X, bottom),                  # body, bottom-right
    (BODY_START - half, bottom),       # body, bottom-left
    (BODY_START + half, top),          # body, top-left
    (HEAD_X, top),                     # body, top-right
    (HEAD_X, MID - HEAD_HALF),         # head, top corner
], fill=ACCENT)

# The trailing slices, getting shorter the further behind they are
right = BODY_START - GAP
for width in SLICES:
    d.polygon(slanted_band(right - width, right), fill=ACCENT)
    right -= width + GAP

ASSETS.mkdir(parents=True, exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(ASSETS / "app_icon.png")
img.save(ASSETS / "app_icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", ASSETS / "app_icon.png", "and app_icon.ico")
