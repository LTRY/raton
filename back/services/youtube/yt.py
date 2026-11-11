import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from yt_dlp import YoutubeDL

from back.core.logging import log_event, log_external

logger = logging.getLogger(__name__)


class YoutubeSearchError(ValueError):
    """A YouTube search that failed; the message is the one shown to the user."""


# YouTube answers HTTP 429 to a burst of requests. The scan spaces its own (`throttle`), but a
# manual download, a playlist import and a channel exploration each run on their own thread and
# would add theirs on top: every yt-dlp call takes a slot here, so only a few run at once whatever
# started them. Media downloads have their own, fewer slots: they last minutes, and a few of them
# must not keep a metadata import or a search waiting.
MAX_CONCURRENT_DOWNLOADS = 2
MAX_CONCURRENT_REQUESTS = 3
# A wait shorter than this is not worth a journal line.
SLOT_WAIT_LOGGED_AFTER_SECONDS = 1.0
_download_slots = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)


@contextmanager
def ytdlp_call(op: str, *, media: bool = False) -> Iterator[None]:
    """Hold a yt-dlp slot (`media`: a download of the video or audio file) and log the call.

    Never call it while already inside one: a thread holding a slot that waits for another could
    deadlock the rest.
    """
    slots = _download_slots if media else _request_slots
    started = time.monotonic()
    with slots:
        waited = time.monotonic() - started
        if waited >= SLOT_WAIT_LOGGED_AFTER_SECONDS:
            log_event(logger, "ytdlp.waited", op=op, waited_ms=round(waited * 1000))
        # A 429 or a scheduled premiere is handled by the callers: a warning, not an error.
        with log_external(
            logger,
            "yt-dlp",
            op,
            expected_failure=lambda exc: (
                is_rate_limit_error(exc) or is_not_yet_available_error(exc)
            ),
        ):
            yield


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
