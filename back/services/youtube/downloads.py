"""yt-dlp downloads of a video's media, subtitles and thumbnail, and the files written next to them."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import webvtt
from yt_dlp import YoutubeDL

from back.models.video import TranscriptStatus
from back.services.common.files import sanitize_filename
from back.services.youtube.yt import extract_video_info, ytdlp_call

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac"}
THUMB_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".json3"}


def build_video_folder(
    media_root: Path, channel_name: str, title: str, published_at: datetime | None
) -> Path:
    date_prefix = (published_at or datetime.now(UTC)).date().isoformat()
    return (
        media_root / sanitize_filename(channel_name) / f"{date_prefix} - {sanitize_filename(title)}"
    )


def download_media(
    video_url: str,
    folder: Path,
    media_type: str = "video",
    video_quality: str = "1080",
) -> dict[str, Any]:
    if media_type not in {"video", "audio"}:
        raise ValueError(f"Unsupported media type: {media_type}")

    folder.mkdir(parents=True, exist_ok=True)
    outtmpl = str(folder / "%(title).120B.%(ext)s")
    allowed_qualities = {"360", "480", "720", "1080", "1440", "2160", "best"}
    if video_quality not in allowed_qualities:
        raise ValueError("Unsupported video quality")
    height_filter = "" if video_quality == "best" else f"[height<={video_quality}]"
    opts = {
        "format": (
            "bestaudio[ext=m4a]/bestaudio/best"
            if media_type == "audio"
            else (
                f"bestvideo{height_filter}[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
                f"best{height_filter}[ext=mp4][vcodec^=avc1]/"
                f"best{height_filter}[ext=mp4]/"
                "best[ext=mp4]/best"
            )
        ),
        "outtmpl": outtmpl,
        "quiet": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "writethumbnail": True,
        "writeinfojson": True,
        "restrictfilenames": True,
    }
    if media_type == "video":
        opts["merge_output_format"] = "mp4"
    if media_type == "audio":
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                # AAC in an m4a container plays on Safari; an m4a source is remuxed, not re-encoded.
                "preferredcodec": "m4a",
            }
        ]
    with ytdlp_call("download_media"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
    return info


PREFERRED_SUBTITLE_LANGUAGES = ("fr", "en")


def choose_subtitle_track(
    info: dict[str, Any], include_auto: bool = True, include_manual: bool = True
) -> tuple[str, bool] | None:
    """The one subtitle track worth fetching, as (yt-dlp language code, is_manual), or None.

    Never a machine translation: since mid-2025 YouTube answers HTTP 429 to the auto-translated
    tracks (`tlang=`) while the original-language ones (`<lang>-orig`) and the creators' own
    subtitles go through. Ranking: creator subtitles in fr/en, original auto captions in fr/en,
    then creator subtitles or original auto captions in any language.
    """
    manual = sorted((info.get("subtitles") or {}).keys()) if include_manual else []
    original = (
        sorted(key for key in (info.get("automatic_captions") or {}) if key.endswith("-orig"))
        if include_auto
        else []
    )

    def preferred(keys: list[str], original: bool) -> str | None:
        for language in PREFERRED_SUBTITLE_LANGUAGES:
            for key in keys:
                # "fr" or a regional variant ("fr-FR"); an original auto caption is exactly "fr-orig".
                if original:
                    matches = key == f"{language}-orig"
                else:
                    matches = key == language or key.startswith(f"{language}-")
                if matches:
                    return key
        return None

    if (key := preferred(manual, original=False)) is not None:
        return key, True
    if (key := preferred(original, original=True)) is not None:
        return key, False
    if manual:
        return manual[0], True
    if original:
        return original[0], False
    return None


def download_subtitles(
    video_url: str,
    folder: Path,
    languages: list[str] | None = None,
    include_auto: bool = True,
    include_manual: bool = True,
    info: dict[str, Any] | None = None,
) -> None:
    """Write the subtitle files; `info` (from `extract_video_info`) saves a second page extraction.

    Without explicit `languages`, the track is chosen by `choose_subtitle_track` and nothing is
    requested when the video has none.
    """
    if not include_auto and not include_manual:
        return
    if languages is None:
        if info is None:
            info = extract_video_info(video_url)
        track = choose_subtitle_track(
            info, include_auto=include_auto, include_manual=include_manual
        )
        if track is None:
            return
        languages, is_manual = track[0], track[1]
        languages = [languages]
        include_manual, include_auto = is_manual, not is_manual
    opts = {
        "skip_download": True,
        "outtmpl": str(folder / "%(title).120B.%(ext)s"),
        "quiet": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "writesubtitles": include_manual,
        "writeautomaticsub": include_auto,
        "subtitleslangs": languages,
        "subtitlesformat": "vtt/best",
        "restrictfilenames": True,
    }
    with ytdlp_call("download_subtitles"), YoutubeDL(opts) as ydl:
        _extract_and_write(ydl, video_url, info)


def _extract_and_write(ydl: YoutubeDL, video_url: str, info: dict[str, Any] | None) -> None:
    if info is None:
        ydl.extract_info(video_url, download=True)
    else:
        ydl.process_ie_result(dict(info), download=True)


def download_thumbnail(video_url: str, folder: Path, info: dict[str, Any] | None = None) -> None:
    opts = {
        "skip_download": True,
        "outtmpl": str(folder / "%(title).120B.%(ext)s"),
        "quiet": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "writethumbnail": True,
        "restrictfilenames": True,
    }
    with ytdlp_call("download_thumbnail"), YoutubeDL(opts) as ydl:
        _extract_and_write(ydl, video_url, info)


def discover_downloaded_files(folder: Path) -> dict[str, Path | None]:
    result: dict[str, Path | None] = {
        "video_path": None,
        "audio_path": None,
        "thumbnail_path": None,
        "metadata_path": None,
        "subtitle_path": None,
    }
    for file in sorted(
        folder.iterdir(), key=lambda item: (item.suffix.lower() != ".vtt", item.name)
    ):
        suffix = file.suffix.lower()
        if suffix in VIDEO_EXTENSIONS and result["video_path"] is None:
            result["video_path"] = file
        elif suffix in AUDIO_EXTENSIONS and result["audio_path"] is None:
            result["audio_path"] = file
        elif suffix in THUMB_EXTENSIONS and result["thumbnail_path"] is None:
            result["thumbnail_path"] = file
        elif suffix == ".json" and result["metadata_path"] is None:
            result["metadata_path"] = file
        elif suffix in SUBTITLE_EXTENSIONS and result["subtitle_path"] is None:
            result["subtitle_path"] = file
    return result


def write_metadata(folder: Path, info: dict[str, Any]) -> Path:
    metadata_path = folder / "metadata.json"
    metadata_path.write_text(
        json.dumps(info, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metadata_path


def dedupe_consecutive_lines(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    previous = ""
    for line in lines:
        normalized = " ".join(line.split()).casefold()
        if normalized and normalized != previous:
            deduped.append(line)
        previous = normalized
    return deduped


def write_transcript(
    folder: Path, subtitle_path: Path | None
) -> tuple[Path | None, TranscriptStatus]:
    if subtitle_path is None or not subtitle_path.exists():
        return None, TranscriptStatus.missing
    transcript_path = folder / "transcript.txt"
    try:
        if subtitle_path.suffix.lower() == ".vtt":
            lines = []
            for caption in webvtt.read(str(subtitle_path)):
                lines.extend(line.strip() for line in caption.text.splitlines() if line.strip())
            lines = dedupe_consecutive_lines(lines)
            transcript_path.write_text("\n".join(lines), encoding="utf-8")
        else:
            transcript_path.write_text(
                subtitle_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8"
            )
    except Exception:
        return None, TranscriptStatus.failed
    return transcript_path, TranscriptStatus.downloaded
