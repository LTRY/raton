"""Durations as `m:ss` / `h:mm:ss` labels and back, shared by the services and the templates."""


def format_duration(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    try:
        total_seconds = int(seconds)
    except TypeError, ValueError:
        return None
    if total_seconds <= 0:
        return None
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_compact_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "0m00"
    try:
        total_seconds = max(int(seconds), 0)
    except TypeError, ValueError:
        return "0m00"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes}m{secs:02d}"
    return f"{minutes}m{secs:02d}"


def parse_duration_label(label: str | None) -> int | None:
    if not label:
        return None
    parts = label.split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        values = [int(part) for part in parts]
    except ValueError:
        return None
    if len(values) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    hours, minutes, seconds = values
    return hours * 3600 + minutes * 60 + seconds
