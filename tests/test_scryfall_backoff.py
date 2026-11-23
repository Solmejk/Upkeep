"""Scryfall requests after a 429 (scryfall._send): wait as long as
Scryfall says (Retry-After), else BACKOFF, and try again — no network,
no real waiting."""

import pytest

import scryfall


class Response:
    def __init__(self, status, retry_after=None):
        self.status_code = status
        self.headers = {"Retry-After": retry_after} if retry_after else {}


@pytest.fixture
def waits(monkeypatch):
    """Every sleep, instead of sleeping; the rate limiter doesn't wait."""
    slept = []
    clock = [1000.0]

    def sleep(seconds):
        slept.append(round(seconds))
        clock[0] += seconds
    monkeypatch.setattr(scryfall.time, "sleep", sleep)
    monkeypatch.setattr(scryfall.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scryfall._rate_limiter, "wait", lambda: None)
    monkeypatch.setattr(scryfall, "_paused_until", 0.0)
    return slept


def answers(monkeypatch, *responses):
    queue = list(responses)
    monkeypatch.setattr(scryfall.requests, "request", lambda *a, **k: queue.pop(0))


def test_retries_after_429_using_retry_after_then_backoff(monkeypatch, waits):
    answers(monkeypatch, Response(429, retry_after="12"), Response(429), Response(200))
    assert scryfall._send("GET", "https://api.scryfall.com/x").status_code == 200
    assert waits == [12, 15]  # Scryfall's 12 s, then the 2nd BACKOFF step


def test_gives_up_after_the_last_backoff(monkeypatch, waits):
    answers(monkeypatch, *[Response(429)] * (len(scryfall.BACKOFF) + 1))
    assert scryfall._send("GET", "https://api.scryfall.com/x").status_code == 429
    assert waits == list(scryfall.BACKOFF)


def test_no_waiting_without_a_429(monkeypatch, waits):
    answers(monkeypatch, Response(200))
    scryfall._send("GET", "https://api.scryfall.com/x")
    assert waits == []
