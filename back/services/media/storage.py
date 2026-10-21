from sqlalchemy import func, select
from sqlalchemy.orm import Session

from back.models.video import Video
from back.services.common.settings import get_global_quota_bytes

AUTO_DOWNLOAD_MIN_FREE_RATIO = 0.2


def get_total_used_bytes(db: Session) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Video.file_size_bytes), 0))) or 0)


def has_auto_download_headroom(db: Session) -> bool:
    quota = get_global_quota_bytes(db)
    if quota <= 0:
        return False
    used = get_total_used_bytes(db)
    return used < quota * (1 - AUTO_DOWNLOAD_MIN_FREE_RATIO)
