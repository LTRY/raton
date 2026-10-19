"""Downloads land in a staging folder next to their final folder, then move there in one step,
so a failed download never leaves a half-filled media folder behind.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.models.video import Video
from app.services.common.files import (
    directory_size,
    move_directory,
    remove_directory,
    unique_sibling_path,
)
from app.services.common.job_log import log_job
from app.services.media.audio_extract import copy_audio_track, extractable_video_file
from app.services.media.media_storage import media_type_for_paths


def staged_folder(final_folder: Path) -> Path:
    return unique_sibling_path(final_folder, "download")


def final_path(path: Path | None, staging: Path, final_folder: Path) -> Path | None:
    if path is None:
        return None
    return final_folder / path.relative_to(staging)


def commit_video_with_files(db: Session, video: Video, staging: Path, final_folder: Path) -> None:
    moved = False
    try:
        if final_folder.exists():
            raise FileExistsError(f"Le dossier média existe déjà: {final_folder}")
        move_directory(staging, final_folder)
        moved = True
        db.add(video)
        db.commit()
    except Exception:
        db.rollback()
        if moved:
            remove_directory(final_folder)
        else:
            remove_directory(staging)
        raise


def merge_staged_files(db: Session, video: Video, staging: Path, final_folder: Path) -> None:
    moved_files: list[Path] = []
    replaced_files: list[tuple[Path, Path]] = []
    backup_folder = unique_sibling_path(final_folder, "replace")
    try:
        final_folder.mkdir(parents=True, exist_ok=True)
        for staged_file in staging.iterdir():
            if not staged_file.is_file():
                continue
            target = final_folder / staged_file.name
            if target.exists():
                backup_folder.mkdir(parents=True, exist_ok=True)
                backup = backup_folder / staged_file.name
                target.replace(backup)
                replaced_files.append((target, backup))
            staged_file.replace(target)
            moved_files.append(target)
        remove_directory(staging)
        db.add(video)
        db.commit()
        remove_directory(backup_folder)
    except Exception:
        db.rollback()
        for target in reversed(moved_files):
            if target.exists():
                target.unlink()
        for target, backup in reversed(replaced_files):
            if backup.exists():
                backup.replace(target)
        remove_directory(staging)
        remove_directory(backup_folder)
        raise


def extract_audio_from_downloaded_video(db: Session, video: Video) -> bool:
    """Add the audio of a video already on disk by copying its track; False leaves the video untouched.

    False means "use yt-dlp": no local video, an audio already there, a track of lower quality than a
    dedicated download, or an ffmpeg failure.
    """
    if video.audio_path:
        return False
    source = extractable_video_file(video)
    if source is None:
        return False
    final_folder = Path(video.folder_path)
    staging = staged_folder(final_folder)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        target = staging / f"{source.stem}.m4a"
        if not copy_audio_track(source, target):
            remove_directory(staging)
            return False
        video.audio_path = str(final_folder / target.name)
        # A new cache entry: restart the 7-day countdown, as a re-download does.
        video.watched_at = None
        video.media_type = media_type_for_paths(
            video.video_path, video.audio_path, video.metadata_path
        )
        merge_staged_files(db, video, staging, final_folder)
        video.file_size_bytes = directory_size(final_folder)
        db.commit()
    except Exception:
        db.rollback()
        remove_directory(staging)
        raise
    log_job(
        db, "downloaded", f"Audio extracted from the video file: {video.title}", video_id=video.id
    )
    return True
