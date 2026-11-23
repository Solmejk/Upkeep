"""Token print sheets (token_print.py): square corners and crop marks."""

from PIL import Image, ImageDraw

import token_print as tp


def rounded_card(border=(20, 20, 20)):
    """A stand-in for a Scryfall print PNG: a bordered card whose corners
    are transparent outside a rounded curve."""
    w, h = 745, 1040
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], radius=tp.CORNER_PX, fill=border + (255,))
    ImageDraw.Draw(img).rectangle([40, 40, w - 41, h - 41], fill=(200, 60, 60, 255))  # the "art"
    return img


def test_corners_are_filled_with_the_border_not_white():
    out = tp.square_corners(rounded_card())
    for corner in ((0, 0), (744, 0), (0, 1039), (744, 1039)):
        assert out.getpixel(corner) == (20, 20, 20)
    assert out.getpixel((372, 520)) == (200, 60, 60)  # the image itself untouched
    assert out.size == (745, 1040)                    # nothing cropped


def test_marks_sit_on_every_cut_line_outside_the_grid():
    marks = tp.crop_marks(tp.PER_PAGE)  # a full page: 2 x 4
    vertical = {x1 for x1, y1, x2, y2 in marks if x1 == x2}
    horizontal = {y1 for x1, y1, x2, y2 in marks if y1 == y2}
    assert vertical == {tp.GRID_X_MM + c * tp.IMAGE_WIDTH_MM for c in range(3)}
    assert horizontal == {tp.GRID_Y_MM + r * tp.IMAGE_HEIGHT_MM for r in range(5)}
    grid = (tp.GRID_X_MM, tp.GRID_Y_MM, tp.GRID_X_MM + tp.GRID_W_MM, tp.GRID_Y_MM + tp.GRID_H_MM)
    for x1, y1, x2, y2 in marks:  # never on a card, always inside the printable area
        inside = grid[0] < (x1 + x2) / 2 < grid[2] and grid[1] < (y1 + y2) / 2 < grid[3]
        assert not inside
        assert 0 <= min(x1, x2) and max(x1, x2) <= tp.AREA_W_MM
        assert 0 <= min(y1, y2) and max(y1, y2) <= tp.AREA_H_MM


def test_a_partial_page_only_marks_its_own_rows():
    marks = tp.crop_marks(3)  # 2 + 1: two rows
    horizontal = {y1 for x1, y1, x2, y2 in marks if y1 == y2}
    assert horizontal == {tp.GRID_Y_MM + r * tp.IMAGE_HEIGHT_MM for r in range(3)}
    assert tp.crop_marks(0) == []


def test_a_page_fills_the_printable_area():
    page = tp.compose_page([tp.square_corners(rounded_card()).rotate(-90, expand=True)] * 3)
    assert page.size == (tp.mm_to_px(tp.AREA_W_MM), tp.mm_to_px(tp.AREA_H_MM))
