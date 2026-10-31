"""Background crawl / index jobs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import sse_response
from app.catalog import get_catalog
from app.jobs import get_runner

router = APIRouter(tags=["Jobs"])


def _require(job_id: str):
    job = get_catalog().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}")
    return job


@router.get("/jobs")
async def list_jobs(workspace_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    return {"jobs": [j.to_dict() for j in get_catalog().list_jobs(workspace_id, limit)]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    return _require(job_id).to_dict()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    """Live progress for a job as server-sent events."""
    _require(job_id)

    async def events():
        async for message in get_runner().subscribe(job_id):
            yield message["event"], message["data"]

    return sse_response(events())


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    _require(job_id)
    return {"cancelled": get_runner().cancel(job_id)}
