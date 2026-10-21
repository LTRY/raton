import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from back.core.logging import log_event
from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video

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


LOG_PAGE_SIZE = 50
# Filter of the logs -> the statuses it keeps (None keeps everything).
LOG_FILTER_STATUSES: dict[str, frozenset[str] | None] = {
    "all": None,
    "errors": frozenset({"failed"}),
    "warnings": frozenset({"warning", "skipped"}),
    "running": frozenset({"queued", "running"}),
}


@dataclass
class LogPage:
    jobs: list[DownloadJob]
    page: int
    total_pages: int
    # Rows matching the filter and the search.
    total: int
    # Over the whole table, the search left out: each filter's rows, and the last 24 hours'.
    filter_counts: dict[str, int]
    recent_counts: dict[str, int]


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filter_counts(counts: dict[str, int]) -> dict[str, int]:
    return {
        key: sum(counts.values())
        if statuses is None
        else sum(counts.get(name, 0) for name in statuses)
        for key, statuses in LOG_FILTER_STATUSES.items()
    }


def log_page(
    db: Session, filter_key: str, query: str, page: int, now: datetime | None = None
) -> LogPage:
    """One page of `download_jobs`, newest first, in SQL: the table only grows.

    The search spans the message, the fiche's title and the channel's name.
    """
    statuses = LOG_FILTER_STATUSES.get(filter_key)
    totals = dict(
        db.execute(select(DownloadJob.status, func.count()).group_by(DownloadJob.status)).all()
    )
    since = (now or datetime.now(UTC)) - timedelta(hours=24)
    recent = dict(
        db.execute(
            select(DownloadJob.status, func.count())
            .where(DownloadJob.created_at >= since)
            .group_by(DownloadJob.status)
        ).all()
    )
    # Outer joins: system jobs have neither a fiche nor a channel.
    statement = (
        select(DownloadJob)
        .outerjoin(DownloadJob.channel)
        .outerjoin(DownloadJob.video)
        .options(contains_eager(DownloadJob.channel), contains_eager(DownloadJob.video))
    )
    if statuses is not None:
        statement = statement.where(DownloadJob.status.in_(statuses))
    query = query.strip()
    if query:
        pattern = _like_pattern(query)
        statement = statement.where(
            or_(
                DownloadJob.message.ilike(pattern, escape="\\"),
                Video.title.ilike(pattern, escape="\\"),
                Channel.name.ilike(pattern, escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    total_pages = max(1, -(-total // LOG_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    jobs = list(
        db.scalars(
            statement.order_by(desc(DownloadJob.created_at), desc(DownloadJob.id))
            .limit(LOG_PAGE_SIZE)
            .offset((page - 1) * LOG_PAGE_SIZE)
        ).unique()
    )
    return LogPage(
        jobs=jobs,
        page=page,
        total_pages=total_pages,
        total=total,
        filter_counts=_filter_counts(totals),
        recent_counts=_filter_counts(recent),
    )
