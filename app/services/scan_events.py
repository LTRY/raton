"""In-memory feed of what the channel scan is doing, read by the settings page to show popups.

Process-local on purpose: the scan runs in the web process (scheduler thread or a background
task), and the feed is only a live view. The durable record stays in `download_jobs`
(`log_job`) and in the last-scan settings keys.
"""

import threading
from collections import deque
from typing import Any

MAX_EVENTS = 500

_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_next_id = 1


def emit(message: str, level: str = "info", final: bool = False) -> None:
    """Append one event; `level` is "info" or "error" (what the popup looks like).

    `final` marks the last event of a scan: a viewer polling the feed stops on it.
    """
    global _next_id
    with _lock:
        _events.append({"id": _next_id, "level": level, "message": message, "final": final})
        _next_id += 1


def events_after(last_id: int) -> tuple[list[dict[str, Any]], int]:
    """Events newer than `last_id`, and the id to ask for next time."""
    with _lock:
        fresh = [dict(event) for event in _events if event["id"] > last_id]
        return fresh, _next_id - 1


def reset() -> None:
    """Forget every event (tests)."""
    global _next_id
    with _lock:
        _events.clear()
        _next_id = 1
