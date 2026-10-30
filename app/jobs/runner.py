"""
In-process background jobs with live progress.

Crawling and embedding take minutes; they used to run inline and block the HTTP
request for their whole duration.  Jobs now run as asyncio tasks and publish
progress events that clients consume over SSE.

Two details that matter:

* Embedding is blocking CPU work, so it runs under ``asyncio.to_thread`` -- if
  it ran on the event loop, the whole API would stall mid-ingest.
* Progress is therefore published from *both* the loop thread (crawling) and
  worker threads (embedding), so publishing is made thread-safe via
  ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from app.catalog import Job, JobStatus, get_catalog, new_id, utcnow

logger = logging.getLogger(__name__)


class JobHandle:
    """Live state for one running job: subscribers plus the latest snapshot."""

    def __init__(self, job: Job):
        self.job = job
        self.subscribers: List[asyncio.Queue] = []
        self.task: Optional[asyncio.Task] = None
        self.cancelled = False

    def snapshot(self) -> Dict[str, Any]:
        return self.job.to_dict()


class JobRunner:
    def __init__(self, max_concurrent: int = 2):
        self._handles: Dict[str, JobHandle] = {}
        self._lock = threading.RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._max_concurrent = max_concurrent

    # ── lifecycle ─────────────────────────────────────────────────────────

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

    async def shutdown(self) -> None:
        with self._lock:
            handles = list(self._handles.values())
        for handle in handles:
            if handle.task and not handle.task.done():
                handle.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await handle.task

    # ── publishing ────────────────────────────────────────────────────────

    def _fanout(self, job_id: str, event: str, payload: Dict[str, Any]) -> None:
        """Runs on the event loop thread."""
        with self._lock:
            handle = self._handles.get(job_id)
        if not handle:
            return
        message = {"event": event, "data": payload}
        for queue in list(handle.subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Dropping progress event for slow subscriber on %s", job_id)

    def publish(self, job_id: str, event: str, payload: Dict[str, Any]) -> None:
        """Thread-safe: callable from the loop or from a worker thread."""
        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            self._fanout(job_id, event, payload)
        else:
            loop.call_soon_threadsafe(self._fanout, job_id, event, payload)

    # ── mutation ──────────────────────────────────────────────────────────

    def update(self, job_id: str, **fields: Any) -> Optional[Job]:
        job = get_catalog().update_job(job_id, **fields)
        if job:
            with self._lock:
                handle = self._handles.get(job_id)
                if handle:
                    handle.job = job
            self.publish(job_id, "progress", job.to_dict())
        return job

    def progress_callback(self, job_id: str, phase: str) -> Callable[[int, int, str], None]:
        """Adapter matching the crawler/indexer ``on_progress`` signature."""

        def _cb(current: int, total: int, message: str) -> None:
            self.update(
                job_id, phase=phase, current=current, total=total, message=message
            )

        return _cb

    # ── submission ────────────────────────────────────────────────────────

    def submit(
        self,
        workspace_id: str,
        kind: str,
        work: Callable[[str], Awaitable[Dict[str, Any]]],
    ) -> Job:
        """
        Register a job and start it. ``work`` receives the job id and returns
        the result dict stored on completion.
        """
        if self._loop is None:
            raise RuntimeError("JobRunner is not bound to an event loop")

        job = get_catalog().create_job(
            Job(id=new_id(), workspace_id=workspace_id, kind=kind, status=JobStatus.QUEUED)
        )
        handle = JobHandle(job)
        with self._lock:
            self._handles[job.id] = handle

        handle.task = self._loop.create_task(self._run(job.id, work))
        return job

    async def _run(
        self, job_id: str, work: Callable[[str], Awaitable[Dict[str, Any]]]
    ) -> None:
        assert self._semaphore is not None
        async with self._semaphore:
            self.update(
                job_id,
                status=JobStatus.RUNNING,
                started_at=utcnow(),
                message="Started",
            )
            try:
                result = await work(job_id)
                self.update(
                    job_id,
                    status=JobStatus.SUCCEEDED,
                    finished_at=utcnow(),
                    message="Completed",
                    result=result,
                )
            except asyncio.CancelledError:
                self.update(
                    job_id,
                    status=JobStatus.CANCELLED,
                    finished_at=utcnow(),
                    message="Cancelled",
                )
                raise
            except Exception as exc:
                logger.exception("Job %s failed", job_id)
                self.update(
                    job_id,
                    status=JobStatus.FAILED,
                    finished_at=utcnow(),
                    message="Failed",
                    error=str(exc),
                )
            finally:
                self.publish(job_id, "end", {"job_id": job_id})

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            handle = self._handles.get(job_id)
        if not handle or not handle.task or handle.task.done():
            return False
        handle.cancelled = True
        handle.task.cancel()
        return True

    # ── subscription ──────────────────────────────────────────────────────

    async def subscribe(self, job_id: str) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream progress events for a job.

        The current state is replayed first, so a late subscriber (or one that
        connects after the job already finished) is never left staring at a
        blank stream.
        """
        job = get_catalog().get_job(job_id)
        if job is None:
            return

        yield {"event": "progress", "data": job.to_dict()}
        if job.is_terminal:
            yield {"event": "end", "data": {"job_id": job_id}}
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            handle = self._handles.get(job_id)
            if handle is None:
                # Finished between the read above and now.
                final = get_catalog().get_job(job_id)
                if final:
                    yield {"event": "progress", "data": final.to_dict()}
                yield {"event": "end", "data": {"job_id": job_id}}
                return
            handle.subscribers.append(queue)

        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keeps proxies from closing an idle connection.
                    yield {"event": "ping", "data": {}}
                    continue
                yield message
                if message["event"] == "end":
                    return
        finally:
            with self._lock:
                handle = self._handles.get(job_id)
                if handle and queue in handle.subscribers:
                    handle.subscribers.remove(queue)


_runner: Optional[JobRunner] = None
_runner_lock = threading.Lock()


def get_runner() -> JobRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            from app.config import get_settings

            _runner = JobRunner(max_concurrent=get_settings().max_concurrent_jobs)
        return _runner
