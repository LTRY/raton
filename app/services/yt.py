import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse, urlunparse

import webvtt
from yt_dlp import YoutubeDL

from app.core.logging import log_external
from app.models.channel import Channel
from app.models.video import TranscriptStatus
from app.services.files import sanitize_filename
from app.services.url_guard import UnsafeUrlError, ensure_public_http_url

logger = logging.getLogger(__name__)


def _ytdlp_call(op: str):
    # A 429 or a scheduled premiere is handled by the callers: a warning, not an error.
    return log_external(
        logger,
        "yt-dlp",
        op,
        expected_failure=lambda exc: is_rate_limit_error(exc) or is_not_yet_available_error(exc),
    )


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac"}
THUMB_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".json3"}
CHANNEL_SECTIONS = {"videos", "shorts"}
CHANNEL_SECTION_ALIASES = {
    "video": "videos",
    "videos": "videos",
    "short": "shorts",
    "shorts": "shorts",
}


# YouTube's own "Type: Channel" search filter, as the `sp` query parameter.
CHANNEL_SEARCH_FILTER = "EgIQAg%3D%3D"
CHANNEL_SEARCH_LIMIT = 8


class ChannelNotFoundError(ValueError):
    pass


def looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc) or value.startswith(
        ("www.", "youtube.com/", "youtu.be/")
    )


def looks_like_channel_handle(value: str) -> bool:
    return value.startswith("@")


def looks_like_bare_channel_handle(value: str) -> bool:
    return (
        bool(value)
        and not value.startswith("@")
        and all(char.isalnum() or char in "._-" for char in value)
    )


def resolve_channel_url(channel_input: str) -> str:
    value = channel_input.strip()
    if looks_like_channel_handle(value):
        handle = value[1:]
        if not handle or any(char.isspace() for char in handle) or "/" in handle:
            raise ChannelNotFoundError(f"Chaîne introuvable pour {value}")
        return f"https://www.youtube.com/{value}"

    if looks_like_url(value):
        if value.startswith(("www.", "youtube.com/", "youtu.be/")):
            return f"https://{value}"
        try:
            return ensure_public_http_url(value)
        except UnsafeUrlError as exc:
            raise ChannelNotFoundError(str(exc)) from exc

    if looks_like_bare_channel_handle(value):
        return f"https://www.youtube.com/@{value}"

    # A free-text name is ambiguous: callers offer `search_channels` candidates
    # instead of letting a guess pick the channel.
    raise ChannelNotFoundError(f"Chaîne introuvable pour {value}")


def is_channel_reference(value: str) -> bool:
    """Whether the input designates one channel (URL or @handle) rather than a name to search."""
    value = value.strip()
    return looks_like_url(value) or looks_like_channel_handle(value)


def search_channels(query: str, limit: int = CHANNEL_SEARCH_LIMIT) -> list[dict[str, Any]]:
    """YouTube channels matching a free-text name, in YouTube's own relevance order."""
    value = query.strip()
    if not value:
        return []
    url = f"https://www.youtube.com/results?search_query={quote_plus(value)}&sp={CHANNEL_SEARCH_FILTER}"
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": limit}
    with _ytdlp_call("search_channels"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    results = []
    for entry in (info.get("entries") if isinstance(info, dict) else None) or []:
        channel_id = str((entry or {}).get("id") or "")
        # The filter is only a request: skip anything that is not a channel.
        if not channel_id.startswith("UC"):
            continue
        handle = entry.get("uploader_id")
        handle = handle if isinstance(handle, str) and handle.startswith("@") else None
        thumbnail = next(
            (item.get("url") for item in entry.get("thumbnails") or [] if item.get("url")), None
        )
        if thumbnail and thumbnail.startswith("//"):
            thumbnail = f"https:{thumbnail}"
        results.append(
            {
                "yt_channel_id": channel_id,
                "name": entry.get("channel") or entry.get("title") or handle or channel_id,
                "handle": handle,
                "url": f"https://www.youtube.com/{handle}"
                if handle
                else f"https://www.youtube.com/channel/{channel_id}",
                "subscriber_count": entry.get("channel_follower_count"),
                "description": (entry.get("description") or "").strip() or None,
                "thumbnail_url": thumbnail,
            }
        )
    return results


def extract_channel_info(channel_input: str) -> dict[str, Any]:
    submitted_value = channel_input.strip()
    strict_handle = looks_like_channel_handle(submitted_value) or looks_like_bare_channel_handle(
        submitted_value
    )
    url = resolve_channel_url(channel_input)
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": 1}
    try:
        with _ytdlp_call("extract_channel_info"), YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        if strict_handle:
            raise ChannelNotFoundError(f"Chaîne introuvable pour {channel_input.strip()}") from exc
        raise
    if not info:
        raise ChannelNotFoundError(f"Chaîne introuvable pour {channel_input.strip()}")
    return {
        "url": url,
        "name": info.get("channel") or info.get("uploader") or info.get("title") or url,
        "yt_channel_id": info.get("channel_id") or info.get("uploader_id") or info.get("id"),
    }


def channel_image_url(thumbnails: list[dict[str, Any]] | None, image_id: str) -> str | None:
    # The uncropped entries are the originals; the numbered ones are crops of them.
    for item in thumbnails or []:
        if item.get("id") == image_id and item.get("url"):
            url = item["url"]
            return f"https:{url}" if url.startswith("//") else url
    return None


def fetch_channel_profile(channel_url: str) -> dict[str, Any]:
    """Description, tags and image URLs of a channel, from the same flat extraction used to add it."""
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": 1}
    with _ytdlp_call("fetch_channel_profile"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    if not info:
        raise ChannelNotFoundError(f"Chaîne introuvable pour {channel_url}")
    thumbnails = info.get("thumbnails")
    return {
        "description": (info.get("description") or "").strip() or None,
        "keywords": [
            tag.strip() for tag in info.get("tags") or [] if isinstance(tag, str) and tag.strip()
        ],
        "avatar_url": channel_image_url(thumbnails, "avatar_uncropped"),
        "banner_url": channel_image_url(thumbnails, "banner_uncropped"),
    }


def count_channel_entries(channel: Channel) -> int | None:
    def count_from_info(info: dict[str, Any]) -> int | None:
        for key in ("playlist_count", "n_entries"):
            value = info.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        return None

    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playlistend": 1,
    }
    with _ytdlp_call("count_channel_entries"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel.url, download=False)

    count = count_from_info(info)
    if count is not None:
        return count

    full_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }
    with _ytdlp_call("count_channel_entries"), YoutubeDL(full_opts) as ydl:
        info = ydl.extract_info(channel.url, download=False)

    count = count_from_info(info)
    if count is not None:
        return count
    entries = info.get("entries")
    return len([entry for entry in entries if entry]) if isinstance(entries, list) else None


def normalized_channel_section(section: str = "videos") -> str:
    normalized = CHANNEL_SECTION_ALIASES.get(section)
    if normalized is None:
        raise ValueError("section must be videos or shorts")
    return normalized


def channel_section_url(url: str, section: str = "videos") -> str:
    section = normalized_channel_section(section)
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and segments[-1] in CHANNEL_SECTIONS:
        segments = segments[:-1]
    path = "/" + "/".join([*segments, section])
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def list_channel_entries(
    channel: Channel, page: int = 1, page_size: int = 25, section: str = "videos"
) -> list[dict[str, Any]]:
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if page_size < 1:
        raise ValueError("page_size must be greater than or equal to 1")

    section_url = channel_section_url(channel.url, section)
    playlist_start = ((page - 1) * page_size) + 1
    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playliststart": playlist_start,
        "playlistend": playlist_start + page_size - 1,
    }
    with _ytdlp_call("list_channel_entries"), YoutubeDL(opts) as ydl:
        info = ydl.extract_info(section_url, download=False)
    return [entry for entry in info.get("entries", []) if entry]


def parse_yt_date(value: str | int | float | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def build_video_folder(
    media_root: Path, channel_name: str, title: str, published_at: datetime | None
) -> Path:
    date_prefix = (published_at or datetime.now(UTC)).date().isoformat()
    return (
        media_root / sanitize_filename(channel_name) / f"{date_prefix} - {sanitize_filename(title)}"
    )


def is_rate_limit_error(exc: BaseException) -> bool:
    """Whether a yt-dlp failure is YouTube throttling us (HTTP 429), so a caller can stop instead of retrying."""
    text = str(exc)
    return "HTTP Error 429" in text or "Too Many Requests" in text


# What yt-dlp says for a premiere or a live event that is scheduled but not started yet.
_NOT_YET_AVAILABLE_MARKERS = (
    "Premieres in",
    "Premiere will begin",
    "This live event will begin in",
)


def is_not_yet_available_error(exc: BaseException) -> bool:
    """Whether a video is listed but scheduled for later: nothing is wrong, the next scan retries it."""
    text = str(exc)
    return any(marker in text for marker in _NOT_YET_AVAILABLE_MARKERS)


def extract_video_info(video_url: str) -> dict[str, Any]:
    opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    with _ytdlp_call("extract_video_info"), YoutubeDL(opts) as ydl:
        return ydl.extract_info(video_url, download=False)


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
    with _ytdlp_call("download_media"), YoutubeDL(opts) as ydl:
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
    with _ytdlp_call("download_subtitles"), YoutubeDL(opts) as ydl:
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
    with _ytdlp_call("download_thumbnail"), YoutubeDL(opts) as ydl:
        _extract_and_write(ydl, video_url, info)


def download_video(video_url: str, folder: Path) -> dict[str, Any]:
    info = download_media(video_url, folder, media_type="video")
    try:
        download_subtitles(video_url, folder)
    except Exception:
        pass
    return info


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
