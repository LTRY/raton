import logging
from datetime import UTC, datetime
from typing import Any

from yt_dlp import YoutubeDL

from back.core.logging import log_external

logger = logging.getLogger(__name__)


class YoutubeSearchError(ValueError):
    """A YouTube search that failed; the message is the one shown to the user."""


def ytdlp_call(op: str):
    # A 429 or a scheduled premiere is handled by the callers: a warning, not an error.
    return log_external(
        logger,
        "yt-dlp",
        op,
        expected_failure=lambda exc: is_rate_limit_error(exc) or is_not_yet_available_error(exc),
    )


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
    with ytdlp_call("extract_video_info"), YoutubeDL(opts) as ydl:
        return ydl.extract_info(video_url, download=False)
