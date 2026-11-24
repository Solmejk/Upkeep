"""progress.py: the sync progress the sidebar shows."""

import progress
import moxfield
import rate_limit
from models.collection import Collection


def test_stage_shows_while_running_and_is_gone_after():
    assert progress.current() is None
    with progress.stage("Decks", total=4, step_seconds=1.2) as s:
        s.advance()
        text, done, total = progress.snapshot()
        assert (done, total) == (1, 4)
        assert text.startswith("Decks: 1 of 4")
        assert "left" in text
    assert progress.snapshot() is None


def test_latest_stage_wins_and_the_earlier_one_returns():
    with progress.stage("Collection pages", total=10):
        with progress.stage("Prices", total=3):
            assert progress.current().name == "Prices"
        assert progress.current().name == "Collection pages"


def test_estimate_never_below_the_request_spacing():
    with progress.stage("Collection pages", total=11, step_seconds=1.2) as s:
        s.update(1)
        assert s.seconds_left() >= 10 * 1.2


def test_unknown_total_is_a_busy_stage():
    with progress.stage("Profile") as s:
        assert s.text() == "Profile…"
        assert progress.snapshot()[2] == 0


def test_stage_is_removed_when_the_work_fails():
    try:
        with progress.stage("Decks", total=2):
            raise RuntimeError("Moxfield down")
    except RuntimeError:
        pass
    assert progress.current() is None


def test_collection_download_reports_each_page(monkeypatch):
    seen = []

    def page(collection_id, number, timeout=10):
        s = progress.current()
        seen.append((s.name, s.done, s.total))
        return {"totalPages": 3, "totalOverall": 3, "data": [{"page": number}]}

    monkeypatch.setattr(moxfield, "fetch_collection_page", page)
    monkeypatch.setattr(moxfield, "_rate_limiter", rate_limit.RateLimiter(interval=0))
    Collection("abc")._fetch_all_pages()
    # page 1 before the total is known, then 1 of 3 and 2 of 3 done when 2 and 3 are fetched
    assert seen == [("Collection pages", 0, 1), ("Collection pages", 1, 3), ("Collection pages", 2, 3)]
    assert progress.current() is None
