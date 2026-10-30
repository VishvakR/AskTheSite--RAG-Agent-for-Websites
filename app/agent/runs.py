"""Which sessions are generating right now, and how to stop them."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Dict, Iterator


class SessionBusy(Exception):
    pass


class RunRegistry:
    """
    One active run per session. A second request while one is streaming would
    interleave two answers into the same history, so it is refused instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, threading.Event] = {}

    @contextmanager
    def claim(self, session_id: str) -> Iterator[threading.Event]:
        with self._lock:
            if session_id in self._runs:
                raise SessionBusy(f"Session {session_id!r} is already answering")
            cancel = threading.Event()
            self._runs[session_id] = cancel
        try:
            yield cancel
        finally:
            with self._lock:
                self._runs.pop(session_id, None)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            event = self._runs.get(session_id)
        if event is None:
            return False
        event.set()
        return True

    def active(self) -> list[str]:
        with self._lock:
            return list(self._runs)


runs = RunRegistry()
