"""moxfield.py's guardrails (Moxfield's terms): no request without the
user-agent, the user-agent sent and stored encrypted, one request at a
time at most once per second, and a 429 / 403 stopping all requests."""

import threading
import time

import pytest

import moxfield
import paths
import rate_limit
import secret_store
from models.collection import Collection


class FakeResponse:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def mox(tmp_path, monkeypatch):
    """moxfield with its secret in a temp folder, no block, no waiting,
    and requests.get recorded instead of sent. Returns the call list;
    set `mox.responses` to a list of FakeResponses to answer with."""
    monkeypatch.setattr(paths, "MOXFIELD_ACCESS_PATH", tmp_path / "moxfield_access.bin")
    monkeypatch.setattr(moxfield, "_user_agent_cache", [])
    monkeypatch.setattr(moxfield, "_rate_limiter", rate_limit.RateLimiter(interval=0))
    moxfield._unblock()
    calls = []

    class State:
        responses = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append({"url": url, "params": dict(params or {}), "headers": headers})
        return State.responses.pop(0) if State.responses else FakeResponse(data={"ok": True})

    monkeypatch.setattr(moxfield.requests, "get", fake_get)
    State.calls = calls
    yield State
    moxfield._unblock()


def test_no_user_agent_means_no_request(mox):
    with pytest.raises(moxfield.MoxfieldError, match="isn't set up"):
        moxfield.fetch_profile("someone")
    assert mox.calls == []


def test_user_agent_is_sent_and_stored_encrypted(mox):
    moxfield.set_user_agent("  Secret-Agent/1.0  ")
    assert moxfield.fetch_profile("someone") == {"ok": True}
    assert mox.calls[0]["headers"]["User-Agent"] == "Secret-Agent/1.0"
    raw = paths.MOXFIELD_ACCESS_PATH.read_bytes()
    assert b"Secret-Agent" not in raw  # encrypted (DPAPI on Windows)
    moxfield._user_agent_cache.clear()  # a new start reads it back from disk
    assert moxfield.user_agent() == "Secret-Agent/1.0"


def test_bad_user_agents_are_rejected(mox):
    for bad in ("", "   ", "line one\nline two", "x" * 600):
        with pytest.raises(ValueError):
            moxfield.set_user_agent(bad)
    assert not moxfield.has_user_agent()


def test_clear_user_agent(mox):
    moxfield.set_user_agent("Secret-Agent/1.0")
    moxfield.clear_user_agent()
    assert not moxfield.has_user_agent()
    assert not paths.MOXFIELD_ACCESS_PATH.exists()


@pytest.mark.parametrize("status", [429, 403])
def test_refusal_stops_all_requests(mox, status):
    moxfield.set_user_agent("Secret-Agent/1.0")
    mox.responses = [FakeResponse(status)]
    with pytest.raises(moxfield.MoxfieldError):
        moxfield.fetch_deck("abc")
    assert moxfield.blocked_for() > 60
    with pytest.raises(moxfield.MoxfieldError, match="paused"):
        moxfield.fetch_deck("def")
    assert len(mox.calls) == 1  # the second request was never sent


def test_retry_after_longer_than_the_block_is_respected(mox):
    moxfield.set_user_agent("Secret-Agent/1.0")
    mox.responses = [FakeResponse(429, headers={"Retry-After": "3600"})]
    with pytest.raises(moxfield.MoxfieldError):
        moxfield.fetch_deck("abc")
    assert moxfield.blocked_for() > 3000


def test_new_user_agent_lifts_a_block(mox):
    moxfield.set_user_agent("Old-Agent/1.0")
    mox.responses = [FakeResponse(403)]
    with pytest.raises(moxfield.MoxfieldError):
        moxfield.fetch_deck("abc")
    moxfield.set_user_agent("New-Agent/1.0")
    assert moxfield.blocked_for() == 0


def test_collection_pages_are_fetched_one_after_another(mox, tmp_path, monkeypatch):
    moxfield.set_user_agent("Secret-Agent/1.0")
    in_flight, overlaps = [0], []
    lock = threading.Lock()

    def page(collection_id, number, timeout=10):
        with lock:
            in_flight[0] += 1
            overlaps.append(in_flight[0])
        time.sleep(0.01)
        with lock:
            in_flight[0] -= 1
        return {"totalPages": 4, "totalOverall": 4, "data": [{"page": number}]}

    monkeypatch.setattr(moxfield, "fetch_collection_page", page)
    data = Collection("abc")._fetch_all_pages()
    assert [d["page"] for d in data["data"]] == [1, 2, 3, 4]
    assert max(overlaps) == 1


def test_rate_limiter_spaces_requests_across_threads():
    limiter = rate_limit.RateLimiter(interval=0.05)
    stamps = []
    lock = threading.Lock()

    def worker():
        limiter.wait()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= 0.04  # a little timer slack


def test_moxfield_interval_keeps_under_one_per_second():
    assert moxfield.REQUEST_INTERVAL >= 1.0
    assert moxfield._rate_limiter.interval >= 1.0


def test_secret_store_unreadable_file_reads_as_missing(tmp_path):
    path = tmp_path / "s.bin"
    path.write_bytes(b"DPAPI1:not really encrypted")
    assert secret_store.load(path) is None
