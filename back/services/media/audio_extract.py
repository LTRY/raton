"""Audio taken from an already downloaded video file instead of a new yt-dlp download.

The audio track of a video downloaded as `bestvideo+bestaudio[ext=m4a]` is the same stream a
dedicated audio download would fetch, so copying it out of the file costs no network and no
re-encoding. A video that came from a progressive fallback format carries a lower-bitrate track:
extracting from it would hand over a degraded audio, so it is left to yt-dlp.
"""

import json
import logging
import os
import subprocess
from pathlib import Path

from back.core.config import local_media_path
from back.models.video import Video

logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT_SECONDS = 300


def video_audio_is_dedicated_stream(metadata_file: Path) -> bool:
    """Whether the video file was merged with a separate AAC audio stream (see module docstring)."""
    try:
        info = json.loads(metadata_file.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    formats = info.get("requested_formats") if isinstance(info, dict) else None
    if not isinstance(formats, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("vcodec") == "none"
        and str(item.get("acodec") or "").startswith("mp4a")
        for item in formats
    )


def extractable_video_file(video: Video) -> Path | None:
    """The local video file whose audio track can be copied out, or None when yt-dlp must be used."""
    if not video.video_path or not video.metadata_path or not video.folder_path:
        return None
    try:
        folder = local_media_path(video.folder_path).resolve()
        source = local_media_path(video.video_path).resolve()
        metadata = local_media_path(video.metadata_path).resolve()
    except OSError:
        return None
    if not source.is_file() or not source.is_relative_to(folder) or not metadata.is_file():
        return None
    return source if video_audio_is_dedicated_stream(metadata) else None


def copy_audio_track(source: Path, target: Path) -> bool:
    """Copy the AAC track of `source` into an m4a at `target`; False when ffmpeg could not."""
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
                "-vn",
                "-c:a",
                "copy",
                "-f",
                "ipod",
                str(partial),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        os.replace(partial, target)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("audio extraction failed for %s: %s", source, exc)
        return False
    finally:
        partial.unlink(missing_ok=True)
