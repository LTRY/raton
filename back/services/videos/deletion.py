"""Deleting a fiche at the person's request: its rows, its folder, and the trace that keeps the
scan from importing it again."""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from back.core.config import local_media_path
from back.core.logging import log_event
from back.models.deleted_video import DeletedVideo
from back.models.video import Video
from back.services.common.files import remove_directory
from back.services.common.settings import get_media_root

logger = logging.getLogger(__name__)


def delete_video(db: Session, video: Video) -> None:
    """Delete the fiche, then its folder.

    The rows go first: a folder that fails to go away is only an orphan on the disk, while a fiche
    left pointing to removed files would be broken.
    """
    video_id, yt_video_id = video.id, video.yt_video_id
    folder = local_media_path(video.folder_path).resolve()
    if db.get(DeletedVideo, yt_video_id) is None:
        db.add(DeletedVideo(yt_video_id=yt_video_id))
    db.delete(video)
    db.commit()

    removed = _remove_fiche_folder(folder, local_media_path(str(get_media_root(db))).resolve())
    log_event(
        logger, "video.deleted", video_id=video_id, yt_video_id=yt_video_id, folder_removed=removed
    )


def _remove_fiche_folder(folder: Path, media_root: Path) -> bool:
    # A stored path is never trusted with an rmtree: only a folder strictly inside the library.
    if folder == media_root or not folder.is_relative_to(media_root):
        return False
    try:
        remove_directory(folder)
    except OSError:
        logger.exception("Could not remove the folder of a deleted fiche: %s", folder)
        return False
    return True
