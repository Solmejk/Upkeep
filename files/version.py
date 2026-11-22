"""The app's version, e.g. "1.0.1" — or "dev" when running from source.

build.py writes it into _build_info.py just for the PyInstaller run
(from --version, or the latest git tag), so a built Upkeep.exe knows its
own version; that file is deleted again afterwards and never committed.
The updater (updater.py) compares this with the newest GitHub release.
"""

try:
    from _build_info import VERSION
except ImportError:
    VERSION = "dev"
