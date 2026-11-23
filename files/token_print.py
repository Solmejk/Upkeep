"""Token print sheets: a Word document (.docx) with N copies of each token
image, ready to print and cut — ported from the standalone TokenPrinter
(Mac/tkinter) script, on A4: images turned 90°, 88 mm wide (= a card's
height, so each prints at real card size), two per row, four rows = 8
tokens per page. Images are Scryfall's full-size PNGs (745x1040, ~300 dpi
at card size), downloaded once into the image cache.

Made for cutting: the cards touch (one cut between two cards), their
rounded corners are filled in with the card's own border colour (square
cards, nothing cropped), and short crop marks stick out from every cut
line into the margin around the grid. Each page is composed as one image
(compose_page) and placed in the document's printable area; the preview
(ui/components/token_sheet_preview.py) draws the same layout.
"""

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.shared import Mm, Pt
from PIL import Image, ImageDraw

import scryfall
from image_cache import get_original_image_path

IMAGE_WIDTH_MM = 88   # the rotated card's width = a card's 88 mm height
IMAGE_HEIGHT_MM = 63  # ... and its height = a card's 63 mm width
PER_ROW = 2
ROWS_PER_PAGE = 4
PER_PAGE = PER_ROW * ROWS_PER_PAGE  # 8
MARGIN_MM = 10
PAGE_W_MM, PAGE_H_MM = 210, 297  # A4
AREA_W_MM = PAGE_W_MM - 2 * MARGIN_MM       # 190: the printable area each page image fills
AREA_H_MM = PAGE_H_MM - 2 * MARGIN_MM - 1   # 276 (1 mm spare so Word never spills onto a new page)
GRID_W_MM = PER_ROW * IMAGE_WIDTH_MM        # 176
GRID_H_MM = ROWS_PER_PAGE * IMAGE_HEIGHT_MM  # 252
GRID_X_MM = (AREA_W_MM - GRID_W_MM) / 2     # 7: the grid is centred in the area
GRID_Y_MM = (AREA_H_MM - GRID_H_MM) / 2     # 12
MARK_LENGTH_MM = 5    # crop marks: from the grid's edge outwards
MARK_WIDTH_MM = 0.25
DPI = 300
CORNER_PX = 33        # Scryfall print PNGs' corner radius (transparent outside the curve)


def mm_to_px(mm: float) -> int:
    return round(mm / 25.4 * DPI)


def grid_cells(count: int) -> tuple[int, int]:
    """(columns, rows) of the grid for `count` cards on one page."""
    count = max(0, min(count, PER_PAGE))
    return min(count, PER_ROW), -(-count // PER_ROW)


def crop_marks(count: int) -> list[tuple[float, float, float, float]]:
    """The page's crop marks as (x1, y1, x2, y2) lines in mm, relative to
    the printable area's top-left: at every vertical cut (above and below
    the grid) and every horizontal cut (left and right of it)."""
    cols, rows = grid_cells(count)
    if not cols:
        return []
    left, top = GRID_X_MM, GRID_Y_MM
    right, bottom = left + cols * IMAGE_WIDTH_MM, top + rows * IMAGE_HEIGHT_MM
    marks = []
    for c in range(cols + 1):
        x = left + c * IMAGE_WIDTH_MM
        marks += [(x, top - MARK_LENGTH_MM, x, top), (x, bottom, x, bottom + MARK_LENGTH_MM)]
    for r in range(rows + 1):
        y = top + r * IMAGE_HEIGHT_MM
        marks += [(left - MARK_LENGTH_MM, y, left, y), (right, y, right + MARK_LENGTH_MM, y)]
    return marks


def print_image_url(token: dict) -> str:
    """Scryfall's full-size PNG of the token's printing (front face)."""
    sid = token.get("scryfall_id")
    if sid:
        return f"https://cards.scryfall.io/png/front/{sid[0]}/{sid[1]}/{sid}.png"
    # decks cached before token ids were stored: derive it from the normal image
    return token.get("image_url", "").replace("/normal/", "/png/").replace(".jpg", ".png")


def print_image_path(token: dict) -> Path | None:
    """Local path of the token's print image, downloading it if needed
    (None if it can't be). These PNGs are ~1.8 MB and the first request
    for one can be slow while Scryfall's servers fetch it, so the download
    gets a longer timeout and two retries."""
    return get_original_image_path(print_image_url(token), f"print_{scryfall.card_key(token)}",
                                   timeout=30, retries=2)


def build_document(tokens_with_counts: list, output_path: Path, progress=None) -> int:
    """Writes the print sheet. tokens_with_counts: [(token, copies)];
    tokens with 0 copies are skipped. progress(done, total): optional
    callback per image. Returns the number of images placed. Raises
    RuntimeError if an image can't be downloaded."""
    images = []  # one entry per copy, in token order
    for token, copies in tokens_with_counts:
        if copies <= 0:
            continue
        path = print_image_path(token)
        if path is None:
            raise RuntimeError(f"Couldn't download the image for {token['name']}.")
        images += [path] * copies

    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Mm(MARGIN_MM)
    section.left_margin = section.right_margin = Mm(MARGIN_MM)
    section.page_width, section.page_height = Mm(PAGE_W_MM), Mm(PAGE_H_MM)

    prepared = {}  # path -> the card, square-cornered and turned (each prepared once)
    done = 0
    for start in range(0, len(images), PER_PAGE):
        cards = []
        for path in images[start:start + PER_PAGE]:
            if path not in prepared:
                prepared[path] = card_for_print(path)
            cards.append(prepared[path])
            done += 1
            if progress:
                progress(done, len(images))
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1
        page = BytesIO()
        compose_page(cards).save(page, format="JPEG", quality=92, dpi=(DPI, DPI))
        p.add_run().add_picture(page, width=Mm(AREA_W_MM), height=Mm(AREA_H_MM))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return len(images)


def compose_page(cards: list) -> Image.Image:
    """One page's printable area at DPI: the cards (from card_for_print)
    in the grid, touching, plus the crop marks; white elsewhere."""
    page = Image.new("RGB", (mm_to_px(AREA_W_MM), mm_to_px(AREA_H_MM)), "white")
    cell_w, cell_h = mm_to_px(IMAGE_WIDTH_MM), mm_to_px(IMAGE_HEIGHT_MM)
    x0, y0 = mm_to_px(GRID_X_MM), mm_to_px(GRID_Y_MM)
    for i, card in enumerate(cards[:PER_PAGE]):
        row, col = divmod(i, PER_ROW)
        page.paste(card.resize((cell_w, cell_h), Image.LANCZOS), (x0 + col * cell_w, y0 + row * cell_h))
    draw = ImageDraw.Draw(page)
    width = max(1, mm_to_px(MARK_WIDTH_MM))
    for x1, y1, x2, y2 in crop_marks(len(cards)):
        draw.line([(mm_to_px(x1), mm_to_px(y1)), (mm_to_px(x2), mm_to_px(y2))], fill="black", width=width)
    return page


def card_for_print(path: Path) -> Image.Image:
    """The token image with square corners, turned 90° clockwise, RGB."""
    return square_corners(Image.open(path)).rotate(-90, expand=True)


def square_corners(img: Image.Image) -> Image.Image:
    """Fills a card image's transparent rounded corners with the card's own
    colour next to each corner (its border, or the art for borderless
    cards) — square corners without cropping anything. Returns RGB."""
    img = img.convert("RGBA")
    w, h = img.size
    r = max(CORNER_PX, round(w * CORNER_PX / 745))  # the radius, scaled to this image's size
    background = Image.new("RGB", img.size, "white")
    draw = ImageDraw.Draw(background)
    for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        dx, dy = (1 if cx == 0 else -1), (1 if cy == 0 else -1)
        # just past the curve, a few pixels in from each of the two edges
        samples = [img.getpixel((cx + dx * (r + 6), cy + dy * 4)), img.getpixel((cx + dx * 4, cy + dy * (r + 6)))]
        colour = tuple(sum(s[i] for s in samples) // len(samples) for i in range(3))
        box = sorted((cx, cx + dx * (r + 2))), sorted((cy, cy + dy * (r + 2)))
        draw.rectangle([box[0][0], box[1][0], box[0][1], box[1][1]], fill=colour)
    background.paste(img, mask=img.split()[3])
    return background
