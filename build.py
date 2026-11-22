"""Builds the Windows app:  python build.py

Runs the tests, then PyInstaller with Upkeep.spec (-> dist/Upkeep.exe),
then Inno Setup with installer/upkeep.iss (-> dist/Upkeep-Setup-<version>.exe,
which installs Upkeep to %LOCALAPPDATA%\\Programs\\Upkeep with Start Menu
shortcuts and an uninstaller). Needs the development requirements
(pip install -r requirements-dev.txt) and, for the installer, Inno Setup 6
(winget install JRSoftware.InnoSetup).

    python build.py --skip-tests       build without running the tests first
    python build.py --no-installer     just the .exe, no Setup.exe
    python build.py --version 1.2.0    the version in the installer's name
                                       (default: the latest git tag, or "dev")
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "dist" / "Upkeep.exe"
ISS = ROOT / "installer" / "upkeep.iss"


def run(*args):
    print("\n>", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def version() -> str:
    if "--version" in sys.argv:
        return sys.argv[sys.argv.index("--version") + 1].lstrip("v")
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        return tag.lstrip("v") or "dev"
    except (OSError, subprocess.CalledProcessError):
        return "dev"


def find_iscc() -> Path | None:
    """Inno Setup's compiler: on PATH, or where its installer puts it."""
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and (Path(base) / "Inno Setup 6" / "ISCC.exe").exists():
            return Path(base) / "Inno Setup 6" / "ISCC.exe"
    return None


def main():
    if "--skip-tests" not in sys.argv:
        run(sys.executable, "-m", "pytest", "-q")
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "Upkeep.spec")
    print(f"\nBuilt {EXE} ({EXE.stat().st_size / 1_000_000:.0f} MB)")

    if "--no-installer" in sys.argv:
        return
    iscc = find_iscc()
    if iscc is None:
        sys.exit("\nInno Setup 6 not found, so no installer was made "
                 "(winget install JRSoftware.InnoSetup, or use --no-installer).")
    ver = version()
    for attempt in range(3):  # antivirus scanning the new file can make this fail now and then
        try:
            run(iscc, "/Q", f"/DAppVersion={ver}", ISS)
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            print("Installer step failed (often antivirus scanning the file); trying again...")
            time.sleep(3)
    setup = ROOT / "dist" / f"Upkeep-Setup-{ver}.exe"
    print(f"Built {setup} ({setup.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\nBuild stopped: {' '.join(map(str, e.cmd))} failed.")
