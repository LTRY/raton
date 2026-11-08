"""Stored, downscaled copies of each video's thumbnail.

YouTube's thumbnail is 1280x720 (~90 KB) while a card shows it at 120-300 px. The copies live in a
`thumbs/` subfolder of the video folder, so that `discover_downloaded_files` (which lists the folder
itself) never takes one for the original, and they go away with the folder.
"""

import logging
import os
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.core.config import local_media_path
from back.models.video import Video

logger = logging.getLogger(__name__)

THUMBNAIL_WIDTHS = (320, 640)
THUMBNAILS_DIRNAME = "thumbs"
FFMPEG_TIMEOUT_SECONDS = 30


def thumbnail_variant_path(folder: Path, width: int) -> Path:
    return folder / THUMBNAILS_DIRNAME / f"{width}.jpg"


def resize_image(source: Path, target: Path, width: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Written next to the target then renamed, so a reader never sees a half-written file.
    partial = target.with_name(f"{target.stem}.partial{target.suffix}")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                # Never upscale a source smaller than the requested width.
                "-vf",
                f"scale='min({width},iw)':-2",
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(partial),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def channel_image_variant(image: Path, width: int) -> Path | None:
    """The copy of a channel's avatar or banner at `width`, made on the first request.

    Stored in a `thumbs/` subfolder next to the image, named after it, and redone when the image is
    newer. None when it cannot be made (no ffmpeg, corrupt image): the caller serves the original.
    """
    target = image.parent / THUMBNAILS_DIRNAME / f"{image.stem}-{width}.jpg"
    try:
        if not target.is_file() or target.stat().st_mtime < image.stat().st_mtime:
            resize_image(image, target, width)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("channel image copy failed for %s: %s", image, exc)
        return None
    return target


def ensure_video_thumbnails(video: Video) -> bool:
    """Create the missing or outdated copies of a video's thumbnail; True when all of them exist afterwards.

    Never raises: a missing ffmpeg or a corrupt image only means the page serves the original thumbnail.
    """
    if not video.thumbnail_path or not video.folder_path:
        return False
    try:
        folder = local_media_path(video.folder_path).resolve()
        source = local_media_path(video.thumbnail_path).resolve()
        if not source.is_file() or not source.is_relative_to(folder):
            return False
        for width in THUMBNAIL_WIDTHS:
            target = thumbnail_variant_path(folder, width)
            if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
                continue
            resize_image(source, target, width)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("thumbnail copies failed for video %s: %s", video.id, exc)
        return False


def backfill_video_thumbnails(db: Session) -> int:
    """Create the copies of every video that has a thumbnail; returns how many videos got new files."""
    created = 0
    for video in db.scalars(
        select(Video).where(Video.thumbnail_path.is_not(None)).order_by(Video.id)
    ):
        folder = local_media_path(video.folder_path)
        missing = any(
            not thumbnail_variant_path(folder, width).is_file() for width in THUMBNAIL_WIDTHS
        )
        if missing and ensure_video_thumbnails(video):
            created += 1
    return created
