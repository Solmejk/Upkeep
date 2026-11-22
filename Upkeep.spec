# PyInstaller build recipe for the single-file Windows app.
# Build with:  python build.py   (or:  python -m PyInstaller Upkeep.spec)
# Output:      dist/Upkeep.exe   (installer/upkeep.iss then wraps it in a Setup.exe)
#
# The .exe carries the code plus the bundled read-only files (icons,
# stylesheet). Your cache and data go to %APPDATA%\Upkeep
# — see files/paths.py.

from pathlib import Path

ROOT = Path(SPECPATH)
FILES = ROOT / "files"

a = Analysis(
    [str(FILES / "main.py")],
    pathex=[str(FILES)],  # the app's modules import each other from files/
    datas=[
        (str(FILES / "assets"), "assets"),
        (str(FILES / "ui" / "style.qss"), "ui"),
    ],
    hiddenimports=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Upkeep",
    icon=str(FILES / "assets" / "app_icon.ico"),
    console=False,  # a windowed app — no console window
    upx=False,      # UPX-compressed exes trip antivirus tools more often
    runtime_tmpdir=None,
)
