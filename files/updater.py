"""In-app updates from GitHub Releases (no Qt here — ui/update_flow.py
drives it from the UI).

    latest_release()    the newest published release, or None
    is_newer(r, cur)    whether release r is newer than the running version
    can_self_update()   true for an installed Upkeep (Setup.exe install);
                        portable copies and source runs open the download
                        page instead
    check()             what the app calls: clean_downloads() + latest_release()
    download(r)         the release's Upkeep-Setup-*.exe (into cache/updates)
    run_installer(p)    starts it silently; it closes Upkeep, replaces the
                        program and reopens it (installer/upkeep.iss)

Publishing a release (git tag vX.Y.Z + push) is what makes an update
appear — see .github/workflows/release.yml.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

import paths
from version import VERSION

REPO = "Solmejk/Upkeep"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
HEADERS = {"User-Agent": f"Upkeep/{VERSION}", "Accept": "application/vnd.github+json"}
TIMEOUT = 10
SETUP_ASSET = re.compile(r"^Upkeep-Setup-.*\.exe$", re.IGNORECASE)
DOWNLOAD_DIR = paths.CACHE_DIR / "updates"


@dataclass
class Release:
    version: str     # "1.0.1" (the tag without its "v")
    page_url: str    # the release's GitHub page
    setup_url: str   # Upkeep-Setup-*.exe download, "" if the release has none
    setup_size: int  # bytes, 0 if unknown
    notes: str       # the release notes (markdown)


def parse_version(text: str):
    """"v1.2.3" / "1.2" -> (1, 2, 3) / (1, 2, 0); None for anything else
    ("dev", "dev-abc1234")."""
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", (text or "").strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer(release: Release, current: str = VERSION) -> bool:
    """True if `release` is newer than `current`. A build without a proper
    version ("dev") counts as older than any release, so it can always
    move onto a real one."""
    new = parse_version(release.version)
    if new is None:
        return False
    old = parse_version(current)
    return old is None or new > old


def latest_release():
    """The newest published release on GitHub (drafts and pre-releases
    don't count), or None if there isn't one yet. Raises on network
    errors."""
    response = requests.get(LATEST_URL, headers=HEADERS, timeout=TIMEOUT)
    if response.status_code == 404:  # no releases yet
        return None
    response.raise_for_status()
    data = response.json()
    setup = next((a for a in data.get("assets", []) if SETUP_ASSET.match(a.get("name", ""))), None)
    return Release(
        version=data.get("tag_name", "").lstrip("v"),
        page_url=data.get("html_url") or RELEASES_PAGE,
        setup_url=setup["browser_download_url"] if setup else "",
        setup_size=setup.get("size", 0) if setup else 0,
        notes=data.get("body") or "",
    )


def can_self_update() -> bool:
    """Only an installed Upkeep (the Setup.exe's uninstaller sits next to
    it) can update itself — running the Setup from a portable copy would
    install a second one, and from source there's no .exe to replace."""
    return paths.FROZEN and (Path(sys.executable).parent / "unins000.exe").exists()


def check() -> "Release | None":
    """What the app runs in the background: tidies old downloads, then
    latest_release()."""
    clean_downloads()
    return latest_release()


def download(release: Release, progress=None) -> Path:
    """Downloads the release's Setup.exe into DOWNLOAD_DIR; progress(done,
    total) is called as it goes (total 0 if unknown). Returns its path."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOAD_DIR / f"Upkeep-Setup-{release.version}.exe"
    partial = dest.with_suffix(".part")
    with requests.get(release.setup_url, headers={"User-Agent": HEADERS["User-Agent"]},
                      stream=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or release.setup_size or 0)
        done = 0
        with open(partial, "wb") as f:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if total and done != total:
        partial.unlink(missing_ok=True)
        raise OSError(f"download incomplete ({done} of {total} bytes)")
    partial.replace(dest)
    return dest


def clean_downloads():
    """Deletes Setups downloaded for earlier updates (they're ~90 MB each);
    one still in use is left for next time."""
    for old in DOWNLOAD_DIR.glob("Upkeep-Setup-*"):
        try:
            old.unlink()
        except OSError:
            pass


def run_installer(setup: Path):
    """Starts the Setup silently (a small progress window, no questions)
    and detached, so it outlives Upkeep. The caller then quits; the Setup
    replaces the program and starts the new version."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
