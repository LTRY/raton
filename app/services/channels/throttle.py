"""Pauses that keep yt-dlp under YouTube's rate limits, and the error raised when it throttles us.

The pauses (min, max seconds) are module-level so tests can zero them; read them through the
module (`throttle.PAUSE_...`), not with `from ... import`, or the zeroing does not reach the caller.
"""

import random
import time

PAUSE_BETWEEN_IMPORTS = (2.0, 5.0)


PAUSE_BETWEEN_CHANNELS = (10.0, 30.0)


# After a channel that only needed a listing (nothing imported): one light request, no need to wait long.
PAUSE_AFTER_LISTING_ONLY = (1.0, 3.0)


class RateLimitedError(Exception):
    """YouTube is throttling us: the caller should stop issuing requests, not retry the next item."""


def pause(bounds: tuple[float, float]) -> None:
    low, high = bounds
    if high > 0:
        time.sleep(random.uniform(low, high))


def pause_between_imports() -> None:
    pause(PAUSE_BETWEEN_IMPORTS)
