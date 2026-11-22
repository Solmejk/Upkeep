"""The in-app updater's version logic and its reading of GitHub's
release data (requests.get is replaced — no network)."""

import pytest

import updater
from updater import Release, is_newer, parse_version


def release(version, **kw):
    return Release(version=version, page_url="", setup_url=kw.get("setup_url", ""), setup_size=0, notes="")


@pytest.mark.parametrize("text, expected", [
    ("1.2.3", (1, 2, 3)), ("v1.2.3", (1, 2, 3)), ("1.2", (1, 2, 0)), ("v2", (2, 0, 0)),
    ("dev", None), ("dev-abc1234", None), ("", None), ("1.2.3-beta", None),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_is_newer_compares_numerically():
    assert is_newer(release("1.0.10"), "1.0.9")      # not as text ("1.0.10" < "1.0.9")
    assert is_newer(release("1.1"), "1.0.5")
    assert not is_newer(release("1.0.1"), "1.0.1")
    assert not is_newer(release("1.0.0"), "1.0.1")


def test_development_builds_can_move_onto_any_release():
    assert is_newer(release("0.1.0"), "dev")
    assert is_newer(release("1.0.0"), "dev-abc1234")
    assert not is_newer(release("nightly"), "dev")  # an unreadable tag is never offered


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_latest_release_finds_the_setup_among_the_assets(monkeypatch):
    data = {
        "tag_name": "v1.4.0", "html_url": "https://github.com/x/y/releases/tag/v1.4.0", "body": "Fixes",
        "assets": [
            {"name": "Upkeep-1.4.0-portable.exe", "browser_download_url": "https://dl/portable", "size": 1},
            {"name": "Upkeep-Setup-1.4.0.exe", "browser_download_url": "https://dl/setup", "size": 90_000_000},
        ],
    }
    monkeypatch.setattr(updater.requests, "get", lambda *a, **kw: FakeResponse(200, data))
    found = updater.latest_release()
    assert found.version == "1.4.0"
    assert found.setup_url == "https://dl/setup"
    assert found.setup_size == 90_000_000
    assert found.notes == "Fixes"


def test_latest_release_without_releases_is_none(monkeypatch):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **kw: FakeResponse(404))
    assert updater.latest_release() is None


def test_a_source_run_cannot_update_itself():
    assert not updater.can_self_update()  # tests run from source: no installed .exe to replace
