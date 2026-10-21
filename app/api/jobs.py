"""`/api/jobs`: the jobs journal (`download_jobs`) and the status of one job, which the actions
that start a download or an import answer with (`status_url`). LLM jobs are `/api/llm-jobs`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.session import get_db
from app.schemas.actions import (
    JobStatusRead,
    RecentJobRead,
)
from app.services.common.job_log import JOB_DONE_STATUSES, recent_jobs
from app.services.jobs.download_requests import JobNotFoundError, job_status

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
