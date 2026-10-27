"""A machine-wide lock serialising the start-up of containers and compose services."""

import contextlib
import fcntl
from collections.abc import Callable, Iterator
from pathlib import Path

LOCK_NAME = ".dazel.lock"


@contextlib.contextmanager
def exclusive_lock(path: Path, on_contended: Callable[[], None] | None = None) -> Iterator[None]:
    """Hold an exclusive ``flock`` on ``path`` (created if missing) for the duration of the block.

    ``on_contended`` is called once, before blocking, when another process holds the lock.

    Worktrees started at the same moment would otherwise race on the shared compose services, the
    shared image and the legacy container. The lock is released when the descriptor closes, so a
    crashed dazel never leaves it held.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if on_contended:
                on_contended()
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
