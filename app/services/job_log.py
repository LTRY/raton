import json
import logging

from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.models.job import DownloadJob
from app.models.video import Video

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


def record_playback_activity(
    db: Session,
    video: Video,
    media_type: str,
    position_seconds: float,
    duration_seconds: float,
    watched_seconds: float,
) -> DownloadJob:
    """Log a playback activity job, used by the web /activity route.

    The dashboard's "Historique" section and playback-time stats both read this
    back via app.web.playback.playback_activity_view, which expects this exact JSON shape.
    """
    position_seconds = max(position_seconds, 0)
    duration_seconds = max(duration_seconds, 0)
    watched_seconds = max(watched_seconds, 0)
    action = "Reprise" if position_seconds >= 3 else "Lecture"
    media_label = "audio" if media_type == "audio" else "vidéo"
    return log_job(
        db,
        "played",
        json.dumps(
            {
                "type": "playback",
                "action": action,
                "media_label": media_label,
                "position_seconds": position_seconds,
                "duration_seconds": duration_seconds,
                "watched_seconds": watched_seconds,
                "title": video.title,
            },
            ensure_ascii=False,
        ),
        channel_id=video.channel_id,
        video_id=video.id,
    )
