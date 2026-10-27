import threading
from pathlib import Path

import pytest

from dazel.lock import exclusive_lock


def test_second_holder_waits_until_the_first_releases(tmp_path: Path) -> None:
    lock = tmp_path / "deep" / "lock"
    acquired = threading.Event()

    def contender() -> None:
        with exclusive_lock(lock):
            acquired.set()

    with exclusive_lock(lock):
        thread = threading.Thread(target=contender)
        thread.start()
        assert not acquired.wait(0.3)
    assert acquired.wait(5)
    thread.join()


def test_contended_lock_reports_it_once_before_waiting(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    waits: list[str] = []
    acquired = threading.Event()

    def contender() -> None:
        with exclusive_lock(lock, lambda: waits.append("waiting")):
            acquired.set()

    with exclusive_lock(lock, lambda: waits.append("first holder")):
        thread = threading.Thread(target=contender)
        thread.start()
        assert not acquired.wait(0.3)
        assert waits == ["waiting"]
    assert acquired.wait(5)
    thread.join()
    assert waits == ["waiting"]


def test_free_lock_does_not_report_contention(tmp_path: Path) -> None:
    waits: list[str] = []
    with exclusive_lock(tmp_path / "lock", lambda: waits.append("waiting")):
        pass
    assert waits == []


def _fail_while_holding(lock: Path) -> None:
    with exclusive_lock(lock):
        msg = "boom"
        raise RuntimeError(msg)


def test_lock_is_released_when_the_block_raises(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    with pytest.raises(RuntimeError, match="boom"):
        _fail_while_holding(lock)
    acquired = threading.Event()

    def contender() -> None:
        with exclusive_lock(lock):
            acquired.set()

    thread = threading.Thread(target=contender)
    thread.start()
    assert acquired.wait(5)
    thread.join()
