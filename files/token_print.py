"""Token print sheets: a Word document (.docx) with N copies of each token
image, ready to print and cut — ported from the standalone TokenPrinter
(Mac/tkinter) script. Same layout: images rotated 90°, 88 mm wide (= a
card's height, so each prints at real card size), two per row, 10 mm
margins — on A4 paper (the script used python-docx's default, US Letter):
2 x 4 = 8 tokens per page. Images are Scryfall's full-size PNGs (745x1040, ~300 dpi at card
size), downloaded once into the image cache.
"""

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.shared import Mm, Pt
from PIL import Image

import scryfall
from image_cache import get_original_image_path

IMAGE_WIDTH_MM = 88   # the rotated card's width = a card's 88 mm height
IMAGE_HEIGHT_MM = 63  # ... and its height = a card's 63 mm width
PER_ROW = 2
MARGIN_MM = 10
PAGE_W_MM, PAGE_H_MM = 210, 297  # A4
ROWS_PER_PAGE = (PAGE_H_MM - 2 * MARGIN_MM) // IMAGE_HEIGHT_MM  # 4
PER_PAGE = PER_ROW * ROWS_PER_PAGE  # 8


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

    prepared = {}  # path -> JPEG bytes (each image rotated / converted once)
    for i in range(0, len(images), PER_ROW):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1
        for n, path in enumerate(images[i:i + PER_ROW]):
            if path not in prepared:
                prepared[path] = _rotated_jpeg(path)
            p.add_run().add_picture(BytesIO(prepared[path]), width=Mm(IMAGE_WIDTH_MM))
            if progress:
                progress(i + n + 1, len(images))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return len(images)


def _rotated_jpeg(path: Path) -> bytes:
    """The image turned 90° clockwise, transparency flattened onto white
    (Scryfall PNGs have transparent rounded corners), as high-quality JPEG."""
    img = Image.open(path).rotate(-90, expand=True)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    buffer = BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()
