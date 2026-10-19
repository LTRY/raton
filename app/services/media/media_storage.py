import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.models.video import Video
from app.services.common.files import directory_size
from app.services.common.job_log import log_job

WATCHED_RATIO = 0.9
RETENTION = timedelta(days=7)
ARCHIVE_MIN_RATING = 4


def media_type_for_paths(
    video_path: str | None, audio_path: str | None, metadata_path: str | None
) -> str:
    if video_path:
        return "video"
    if audio_path:
        return "audio"
    if metadata_path:
        return "metadata"
    return "metadata"


def mark_watched_if_complete(
    video: Video, position_seconds: float, duration_seconds: float, now: datetime | None = None
) -> bool:
    """Start the retention countdown the first time playback reaches WATCHED_RATIO.

    Does not commit. The date is set once and never moved by playback, so replaying a video
    doesn't postpone its deletion. A new download adding a format resets it to
    NULL (see `media_import`), restarting the countdown.
    """
    if not (math.isfinite(position_seconds) and math.isfinite(duration_seconds)):
        return False
    if video.watched_at is not None or duration_seconds <= 0:
        return False
    if position_seconds / duration_seconds < WATCHED_RATIO:
        return False
    video.watched_at = now or datetime.now(UTC)
    return True


def delete_video_media_asset(video: Video, media_type: str) -> None:
    """Delete one format's file; raise ValueError if already absent or outside the video folder."""
    if media_type not in {"video", "audio"}:
        raise ValueError("Le format doit être vidéo ou audio.")

    media_path = video.video_path if media_type == "video" else video.audio_path
    if not media_path:
        raise ValueError("Ce fichier média est déjà absent.")

    folder = local_media_path(video.folder_path).resolve()
    media = local_media_path(media_path).resolve()
    if not media.is_relative_to(folder):
        raise ValueError("Chemin média invalide.")
    media.unlink(missing_ok=True)

    if media_type == "video":
        video.video_path = None
    else:
        video.audio_path = None
    video.media_type = media_type_for_paths(video.video_path, video.audio_path, video.metadata_path)
    video.file_size_bytes = directory_size(folder)


def delete_video_media_file(db: Session, video: Video, media_type: str) -> None:
    """Delete one format's file at the person's request, and commit; ValueError when refused."""
    try:
        delete_video_media_asset(video, media_type)
    except ValueError:
        db.rollback()
        raise
    db.commit()


def purge_watched_media(db: Session, now: datetime | None = None) -> int:
    """Delete the media files of videos watched more than RETENTION ago.

    Videos rated ARCHIVE_MIN_RATING or more are archived and never touched. The
    row, thumbnail, metadata, transcript and notes stay. Each file is committed
    separately so a failure leaves the database matching what is on disk.
    """
    cutoff = (now or datetime.now(UTC)) - RETENTION
    videos = db.scalars(
        select(Video).where(
            Video.watched_at.is_not(None),
            Video.watched_at < cutoff,
            Video.rating < ARCHIVE_MIN_RATING,
            or_(Video.video_path.is_not(None), Video.audio_path.is_not(None)),
        )
    ).all()

    purged = 0
    for video in videos:
        video_id, channel_id = video.id, video.channel_id
        failed = False
        for media_type in ("video", "audio"):
            if not (video.video_path if media_type == "video" else video.audio_path):
                continue
            try:
                delete_video_media_asset(video, media_type)
                db.commit()
            except (ValueError, OSError) as exc:
                db.rollback()
                log_job(
                    db,
                    "failed",
                    f"Suppression du cache impossible ({media_type}) : {exc}",
                    channel_id=channel_id,
                    video_id=video_id,
                )
                failed = True
                break
        if failed:
            continue
        log_job(
            db,
            "purged",
            "Fichiers supprimés du cache : vidéo vue à plus de 90 % depuis plus de 7 jours.",
            channel_id=channel_id,
            video_id=video_id,
        )
        purged += 1
    return purged
