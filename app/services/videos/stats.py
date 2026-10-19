"""Library counters for /settings and `GET /api/stats`."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import Video
from app.services.common.settings import get_global_quota_bytes
from app.services.media.storage import get_total_used_bytes


def library_counts(db: Session) -> dict:
    """Library counters and storage gauge: how many channels, fiches, files and bytes."""
    has_media = (Video.video_path.is_not(None)) | (Video.audio_path.is_not(None))
    is_short = Video.url.contains("/shorts/")
    used_bytes = get_total_used_bytes(db)
    quota_bytes = get_global_quota_bytes(db)
    return {
        "channel_count": db.scalar(select(func.count(Channel.id))) or 0,
        "rated_channel_count": db.scalar(select(func.count(Channel.id)).where(Channel.rating > 0))
        or 0,
        "video_count": db.scalar(select(func.count(Video.id))) or 0,
        "regular_video_count": db.scalar(
            select(func.count(Video.id)).where(~is_short).where(has_media)
        )
        or 0,
        "short_count": db.scalar(select(func.count(Video.id)).where(is_short).where(has_media))
        or 0,
        "downloaded_media_count": db.scalar(select(func.count(Video.id)).where(has_media)) or 0,
        "transcript_count": db.scalar(
            select(func.count(Video.id)).where(Video.transcript_path.is_not(None))
        )
        or 0,
        "used_bytes": used_bytes,
        "quota_bytes": quota_bytes,
        "storage_percent": round(min((used_bytes / quota_bytes) * 100, 100), 2)
        if quota_bytes > 0
        else 0,
    }
