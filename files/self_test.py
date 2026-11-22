"""`--self-test`: checks that a packaged build has everything it needs —
the bundled icons and stylesheet, the libraries features load only when
used (pdfplumber for Cardmarket PDFs, python-docx + Pillow for the Token
Printer), and a writable data folder. No network, no window.

    Upkeep.exe --self-test     (or: python files/main.py --self-test)

Writes a report to <your folder>/self_test.txt (a windowed .exe has no
console) and exits 0 if everything passed, 1 if not. The release build
on GitHub runs this on every .exe it makes.
"""

import io
import sys
import traceback

import paths


def _bundled_files():
    missing = [p.name for p in (paths.STYLE_PATH, paths.APP_ICON_PATH, paths.ASSETS_DIR / "sort.png")
               if not p.exists()]
    assert not missing, f"missing bundled files: {missing}"


def _writable_folder():
    paths.USER_ROOT.mkdir(parents=True, exist_ok=True)
    probe = paths.USER_ROOT / ".write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _pillow():
    from PIL import Image
    Image.open(paths.APP_ICON_PATH).convert("RGB").rotate(-90, expand=True)


def _word_documents():
    from docx import Document
    from docx.shared import Mm
    doc = Document()  # needs python-docx's bundled default template
    doc.sections[0].page_width = Mm(210)
    doc.save(io.BytesIO())


def _pdf_reading():
    import pdfplumber
    from PIL import Image
    pdf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(pdf, format="PDF")  # a one-page PDF
    pdf.seek(0)
    with pdfplumber.open(pdf) as doc:
        assert len(doc.pages) == 1


def _app_modules():
    import importlib
    for name in ("cardmarket", "deck_import", "token_print", "scryfall_prices", "ui.main_window"):
        importlib.import_module(name)  # each must import cleanly in the build
    from models import game_tracker
    game_tracker.GameTracker(paths.USER_ROOT / ".self_test_tracker.json")


CHECKS = [
    ("bundled icons and stylesheet", _bundled_files),
    ("writable data folder", _writable_folder),
    ("Pillow (images)", _pillow),
    ("python-docx (token sheets)", _word_documents),
    ("pdfplumber (Cardmarket PDFs)", _pdf_reading),
    ("app modules", _app_modules),
]


def run() -> int:
    """Runs every check, writes the report, returns the exit code."""
    lines = [f"Upkeep self-test ({'packaged' if paths.FROZEN else 'from source'})",
             f"data folder: {paths.USER_ROOT}", ""]
    failed = 0
    for name, check in CHECKS:
        try:
            check()
            lines.append(f"PASS  {name}")
        except Exception:
            failed += 1
            lines.append(f"FAIL  {name}\n" + traceback.format_exc())
    lines += ["", "all checks passed" if not failed else f"{failed} check(s) failed"]
    report = "\n".join(lines)
    try:
        paths.USER_ROOT.mkdir(parents=True, exist_ok=True)
        (paths.USER_ROOT / "self_test.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout:  # from source: also on the console
        print(report)
    return 1 if failed else 0
