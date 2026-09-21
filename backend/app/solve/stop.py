"""Ask a blocking solver to give up, from another thread.

`Solve()` holds the worker. Cancellation is a flag on the run; this is how
that flag reaches a library that only listens for StopSearch / InterruptSolve
on a different thread than the one inside `Solve()`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def interrupt_when(
    should_stop: Callable[[], bool] | None, interrupt: Callable[[], None]
) -> Iterator[None]:
    if should_stop is None:
        yield
        return
    if should_stop():
        interrupt()
        yield
        return
    done = threading.Event()

    def watch() -> None:
        while not done.wait(0.2):
            if should_stop():
                interrupt()
                return

    threading.Thread(target=watch, daemon=True, name="solver-stop").start()
    try:
        yield
    finally:
        done.set()
