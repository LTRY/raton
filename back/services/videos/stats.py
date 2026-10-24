"""Library counters for /settings and `GET /api/stats`."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.user import UserChannel
from back.models.video import Video
from back.services.common.settings import get_global_quota_bytes
from back.services.common.user_state import channel_rating, channel_state_join
from back.services.media.storage import get_total_used_bytes


def library_counts(db: Session, user_id: int) -> dict:
    """Library counters and storage gauge: how many channels (rated by the user), fiches, files
    and bytes."""
    has_media = (Video.video_path.is_not(None)) | (Video.audio_path.is_not(None))
    is_short = Video.url.contains("/shorts/")
    used_bytes = get_total_used_bytes(db)
    quota_bytes = get_global_quota_bytes(db)
    return {
        "channel_count": db.scalar(select(func.count(Channel.id))) or 0,
        "rated_channel_count": db.scalar(
            select(func.count(Channel.id))
            .outerjoin(UserChannel, channel_state_join(user_id))
            .where(channel_rating > 0)
        )
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
