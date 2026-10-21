"""`/api/jobs`: the jobs journal (`download_jobs`) and the status of one job, which the actions
that start a download or an import answer with (`status_url`). LLM jobs are `/api/llm-jobs`.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.db.session import get_db
from back.schemas.actions import (
    JobStatusRead,
    LogChannelRead,
    LogPageRead,
    LogRowRead,
    LogVideoRead,
    RecentJobRead,
)
from back.services.common.job_log import (
    JOB_DONE_STATUSES,
    log_page,
    recent_jobs,
)
from back.services.jobs.download_requests import JobNotFoundError, cancel_job, job_status

router = APIRouter(prefix="/api", tags=["Jobs"])


@router.get("/jobs", response_model=list[RecentJobRead], responses=error_responses(422))
def list_jobs(
    status: list[str] = Query(default=[]), db: Session = Depends(get_db)
) -> list[RecentJobRead]:
    """The 100 latest jobs, newest first; `status` (repeatable) keeps only those statuses."""
    return [
        RecentJobRead(
            id=job.id,
            status=job.status,
            message=job.message,
            channel_id=job.channel_id,
            video_id=job.video_id,
            created_at=job.created_at,
            done=job.status in JOB_DONE_STATUSES,
        )
        for job in recent_jobs(db, statuses=status)
    ]


@router.get("/logs", response_model=LogPageRead, responses=error_responses(422))
def get_logs(
    filter: Literal["all", "errors", "warnings", "running"] = "all",
    q: str = "",
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> LogPageRead:
    """The journal page by page; `filter` is all, errors, warnings or running, `q` searches the
    message, the fiche's title and the channel's name."""
    logs = log_page(db, filter, q, page)
    return LogPageRead(
        rows=[
            LogRowRead(
                id=job.id,
                status=job.status,
                message=job.message,
                channel_id=job.channel_id,
                video_id=job.video_id,
                created_at=job.created_at,
                done=job.status in JOB_DONE_STATUSES,
                video=LogVideoRead(id=job.video.id, title=job.video.title) if job.video else None,
                channel=LogChannelRead(id=job.channel.id, name=job.channel.name)
                if job.channel
                else None,
            )
            for job in logs.jobs
        ],
        page=logs.page,
        total_pages=logs.total_pages,
        total=logs.total,
        filter_counts=logs.filter_counts,
        last_24h_counts=logs.recent_counts,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusRead,
    response_model_exclude_none=True,
    responses=error_responses(404, 422),
)
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return job_status(db, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobStatusRead,
    response_model_exclude_none=True,
    responses=error_responses(404, 422),
)
def cancel(job_id: int, db: Session = Depends(get_db)) -> dict:
    """Stop a channel exploration: it stops before its next video."""
    try:
        return cancel_job(db, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
