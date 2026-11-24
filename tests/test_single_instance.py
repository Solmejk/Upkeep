"""single_instance: a second Upkeep finds the first, asks it to show its
window, and a lock left by a killed Upkeep is taken over. Uses a real
second process (with its own lock / server names, not the app's)."""

import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtNetwork")
import single_instance  # noqa: E402

FILES = Path(__file__).resolve().parent.parent / "files"

CHILD = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtCore import QCoreApplication, QTimer
    import single_instance
    app = QCoreApplication([])
    assert single_instance.acquire(sys.argv[2]) is not None
    def shown():
        print("shown", flush=True)
        app.quit()
    requests = single_instance.ShowRequests(shown, server_name=sys.argv[3])
    print("ready", flush=True)
    QTimer.singleShot(20000, app.quit)  # never hang the test run
    app.exec()
""")


@pytest.fixture
def names(tmp_path):
    return str(tmp_path / "test.lock"), f"upkeep-test-{uuid.uuid4().hex}"


def start_child(lock, server):
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(FILES), lock, server],
                             stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    return child


def test_second_start_finds_the_first_and_shows_it(names):
    lock, server = names
    child = start_child(lock, server)
    try:
        assert single_instance.acquire(lock) is None  # taken by the running one
        assert single_instance.notify_running(server)
        assert child.stdout.readline().strip() == "shown"
        child.wait(10)
    finally:
        child.kill()


def test_lock_of_a_killed_instance_is_taken_over(names):
    lock, server = names
    child = start_child(lock, server)
    child.kill()
    child.wait(10)
    held = single_instance.acquire(lock)
    assert held is not None
    held.unlock()


def test_nothing_running_means_no_answer(names):
    _, server = names
    assert not single_instance.notify_running(server, timeout_ms=200)
