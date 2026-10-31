"""Consume a blocking iterator from async code without blocking the loop."""

from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator, Callable, Iterator, Optional, TypeVar

T = TypeVar("T")

_DONE = object()


async def iterate_in_thread(
    factory: Callable[[], Iterator[T]],
    cancel: Optional[threading.Event] = None,
) -> AsyncIterator[T]:
    """
    Run ``factory()`` in a worker thread and yield its items here.

    Provider SDKs stream over blocking HTTP, so each turn runs in a thread and
    hands items back through a queue. The worker checks *cancel* (and whether
    the consumer has gone away) between items and closes the underlying
    iterator, which closes the HTTP stream instead of letting it run on.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def put(item, exc=None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (item, exc))
        except RuntimeError:  # loop already closed
            stop.set()

    def produce() -> None:
        iterator = None
        try:
            iterator = factory()
            for item in iterator:
                if stop.is_set() or (cancel is not None and cancel.is_set()):
                    break
                put(item)
        except BaseException as exc:  # surfaced to the consumer
            put(_DONE, exc)
            return
        finally:
            close = getattr(iterator, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass
        put(_DONE)

    loop.run_in_executor(None, produce)
    try:
        while True:
            item, exc = await queue.get()
            if item is _DONE:
                if exc is not None:
                    raise exc
                return
            yield item
    finally:
        stop.set()
