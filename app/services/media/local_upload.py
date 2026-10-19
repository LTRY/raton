"""Import of a media file dropped by the user (no YouTube involved).

The file is streamed to a staging folder next to its final folder, then moved in one step, like a
download (see `app/services/channels/scanner.py`). Local videos live under a pseudo-channel so that cards,
playback and filters need no special case.
"""

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import TranscriptStatus, Video
from app.services.files import move_directory, sanitize_filename, unique_sibling_path
from app.services.media.thumbnails import ensure_video_thumbnails
from app.services.settings import get_media_root
from app.services.youtube.view_counts import parse_duration_seconds
from app.services.youtube.yt import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

LOCAL_CHANNEL_URL = "local://files"
LOCAL_CHANNEL_NAME = "Fichiers locaux"
LOCAL_FOLDER_NAME = "Local"
FFMPEG_TIMEOUT_SECONDS = 60
COPY_CHUNK_BYTES = 1024 * 1024


class LocalUploadError(ValueError):
    """The dropped file cannot be imported; the message is shown to the user."""


def media_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    raise LocalUploadError("Format non pris en charge : dépose un fichier vidéo ou audio.")


def get_or_create_local_channel(db: Session) -> Channel:
    channel = db.scalar(select(Channel).where(Channel.url == LOCAL_CHANNEL_URL))
    if channel is None:
        # Both bells stay off (their default): nothing to scan.
        channel = Channel(url=LOCAL_CHANNEL_URL, name=LOCAL_CHANNEL_NAME)
        db.add(channel)
        db.flush()
    return channel


def _probe_duration_seconds(path: Path) -> int | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        return parse_duration_seconds(json.loads(result.stdout).get("format", {}).get("duration"))
    except OSError, subprocess.SubprocessError, ValueError:
        return None


def _extract_thumbnail(video_file: Path, target: Path, duration: int | None) -> bool:
    # A frame a little way in avoids the black first frame many files start with.
    seek = str(min(5, duration // 2)) if duration else "0"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                seek,
                "-i",
                str(video_file),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        return target.is_file()
    except OSError, subprocess.SubprocessError:
        return False


def import_local_media(
    db: Session,
    filename: str,
    source: BinaryIO,
) -> tuple[Video, bool]:
    """Store an uploaded file and create its Video row; returns (video, created).

    A file whose content was already imported returns the existing row with created=False.
    """
    kind = media_kind(filename)
    suffix = Path(filename).suffix.lower()
    title = Path(filename).stem.strip() or "Fichier local"
    safe_title = sanitize_filename(title)
    root = get_media_root(db)
    local_root = root / LOCAL_FOLDER_NAME
    local_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    final_folder = local_root / f"{now:%Y-%m-%d} - {safe_title}"
    if final_folder.exists():
        final_folder = local_root / f"{now:%Y-%m-%d} - {safe_title} {now:%H%M%S}"
    staging = unique_sibling_path(final_folder, "upload")
    staging.mkdir(parents=True)
    media_name = f"{safe_title}{suffix}"
    staged_file = staging / media_name

    try:
        digest = hashlib.sha1()
        with staged_file.open("wb") as out:
            while chunk := source.read(COPY_CHUNK_BYTES):
                digest.update(chunk)
                out.write(chunk)
        size = staged_file.stat().st_size
        if size == 0:
            raise LocalUploadError("Le fichier est vide.")

        yt_video_id = f"local:{digest.hexdigest()}"
        existing = db.scalar(select(Video).where(Video.yt_video_id == yt_video_id))
        if existing is not None:
            shutil.rmtree(staging, ignore_errors=True)
            return existing, False

        duration = _probe_duration_seconds(staged_file)
        thumbnail_name = None
        if kind == "video" and _extract_thumbnail(staged_file, staging / "thumbnail.jpg", duration):
            thumbnail_name = "thumbnail.jpg"

        move_directory(staging, final_folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    media_path = str(final_folder / media_name)
    channel = get_or_create_local_channel(db)
    video = Video(
        channel_id=channel.id,
        yt_video_id=yt_video_id,
        title=title[:500],
        url=yt_video_id,
        media_type=kind,
        # Postgres only accepts "auto" or "manual" here (ck_videos_download_source, migration 0008).
        download_source="manual",
        imported_via_form=True,
        published_at=now,
        downloaded_at=now,
        folder_path=str(final_folder),
        video_path=media_path if kind == "video" else None,
        audio_path=media_path if kind == "audio" else None,
        thumbnail_path=str(final_folder / thumbnail_name) if thumbnail_name else None,
        transcript_status=TranscriptStatus.missing,
        file_size_bytes=size,
        duration_seconds=duration,
    )
    db.add(video)
    try:
        db.commit()
    except BaseException:
        db.rollback()
        shutil.rmtree(final_folder, ignore_errors=True)
        raise
    if video.thumbnail_path:
        ensure_video_thumbnails(video)
    return video, True
