"""Channel exploration: the metadata import of a whole channel, followed and stopped from its queue row."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.models.job import DownloadJob
from back.models.video import Video

# Statuses of the queue row of a channel import job, the only ones that list the videos it brought in.
CHANNEL_IMPORT_PROGRESS_STATUSES = {"queued", "running", "metadata", "cancelled"}
CHANNEL_IMPORT_PROGRESS_LIMIT = 200


def is_channel_exploration(job: DownloadJob) -> bool:
    return job.channel_id is not None and job.video_id is None


def cancel_channel_exploration(db: Session, job: DownloadJob) -> None:
    """Stop a channel exploration: the running import notices it before its next video."""
    if is_channel_exploration(job) and job.status in {"queued", "running"}:
        job.status = "cancelled"
        job.message = "Exploration arrêtée."
        db.commit()


def channel_exploration_videos(db: Session, job: DownloadJob) -> list[dict] | None:
    """Fiches an exploration has imported so far, or None for any other job."""
    if not is_channel_exploration(job) or job.status not in CHANNEL_IMPORT_PROGRESS_STATUSES:
        return None
    # The import logs one "metadata" row per video, after the queue row: ids are monotonic, so
    # "newer than the queue row" is enough, with no clock comparison.
    imported = db.execute(
        select(Video.id, Video.title)
        .join(DownloadJob, DownloadJob.video_id == Video.id)
        .where(
            DownloadJob.status == "metadata",
            DownloadJob.channel_id == job.channel_id,
            DownloadJob.id > job.id,
        )
        .order_by(DownloadJob.id)
        .limit(CHANNEL_IMPORT_PROGRESS_LIMIT)
    ).all()
    return [{"id": video_id, "title": title} for video_id, title in imported]
