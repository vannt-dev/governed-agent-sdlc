"""Process-scoped, reentrant run locks; the OS releases them after a crash."""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_held = threading.local()


@contextmanager
def run_lock(run_dir: Path) -> Iterator[None]:
    path = run_dir.resolve() / ".run.lock"
    held: set[str] = getattr(_held, "paths", set())
    key = str(path)
    if key in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError(
                f"Review run is busy: {run_dir.name}. Retry after its writer finishes."
            ) from exc
        held.add(key)
        _held.paths = held
        try:
            yield
        finally:
            held.remove(key)
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
