"""`videos.view_count` and `videos.duration_seconds`: the two numbers of metadata.json a list needs.

They live in columns so a list sorts on them in SQL and a card shows them without parsing the (~140 KB)
metadata.json of every video.
"""

import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.models.video import Video

BACKFILL_BATCH_SIZE = 200


def parse_view_count(value) -> int | None:
    try:
        return max(int(value), 0)
    except TypeError, ValueError:
        return None


def parse_duration_seconds(value) -> int | None:
    try:
        return max(int(float(value)), 0)
    except TypeError, ValueError:
        return None


def backfill_view_counts(db: Session) -> int:
    """Fill `view_count` and `duration_seconds` of the videos that have a metadata file but lack one of
    them; returns how many videos were updated.

    A readable file without the value gets 0, so it is not read again at the next startup. An unreadable
    file (media root not mounted) keeps NULL and is retried.
    """
    updated = 0
    last_id = 0
    while True:
        videos = list(
            db.scalars(
                select(Video)
                .where(
                    Video.id > last_id,
                    or_(Video.view_count.is_(None), Video.duration_seconds.is_(None)),
                    Video.metadata_path.is_not(None),
                )
                .order_by(Video.id)
                .limit(BACKFILL_BATCH_SIZE)
            )
        )
        if not videos:
            return updated
        for video in videos:
            last_id = video.id
            try:
                data = json.loads(local_media_path(video.metadata_path).read_text(encoding="utf-8"))
            except OSError, ValueError:
                continue
            if not isinstance(data, dict):
                data = {}
            count = parse_view_count(data.get("view_count"))
            duration = parse_duration_seconds(data.get("duration"))
            video.view_count = count if count is not None else 0
            video.duration_seconds = duration if duration is not None else 0
            updated += 1
        db.commit()
