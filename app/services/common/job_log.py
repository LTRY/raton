import logging

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.models.job import DownloadJob

logger = logging.getLogger(__name__)

JOB_STATUS_LOG_LEVELS = {
    "failed": logging.ERROR,
    "warning": logging.WARNING,
    "skipped": logging.WARNING,
}


def log_job(
    db: Session,
    status: str,
    message: str,
    channel_id: int | None = None,
    video_id: int | None = None,
) -> DownloadJob:
    job = DownloadJob(channel_id=channel_id, video_id=video_id, status=status, message=message)
    db.add(job)
    db.commit()
    # Mirror every `/logs` row into the journal; a playback row carries a JSON payload, not text.
    log_event(
        logger,
        "job.record",
        level=JOB_STATUS_LOG_LEVELS.get(status, logging.INFO),
        status=status,
        message="" if status == "played" else message,
        channel_id=channel_id,
        video_id=video_id,
    )
    return job


# Statuses after which a job no longer changes.
JOB_DONE_STATUSES = {"downloaded", "metadata", "failed", "cancelled"}


def recent_jobs(
    db: Session, limit: int = 100, statuses: list[str] | None = None
) -> list[DownloadJob]:
    """The latest `download_jobs` rows (of these statuses), newest first; bounded because the
    table only grows."""
    query = select(DownloadJob)
    if statuses:
        query = query.where(DownloadJob.status.in_(statuses))
    return list(db.scalars(query.order_by(desc(DownloadJob.created_at)).limit(limit)))
