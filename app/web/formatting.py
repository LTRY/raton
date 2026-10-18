from collections.abc import Iterable
from datetime import datetime

from app.web.shared import templates


def format_long_duration(seconds: int | float | None) -> str | None:
    """Total running time in words ("21 h 40 min"), for a playlist header."""
    try:
        total_minutes = int(seconds or 0) // 60
    except TypeError, ValueError:
        return None
    if total_minutes <= 0:
        return None
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


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


def format_two_unit_duration(seconds: int | float | None) -> str:
    try:
        total_minutes = max(int(seconds or 0), 0) // 60
    except TypeError, ValueError:
        total_minutes = 0
    total_hours, minutes = divmod(total_minutes, 60)
    days, hours = divmod(total_hours, 24)
    if days:
        return f"{days}d{hours}h" if hours else f"{days}d"
    if total_hours:
        return f"{total_hours}h{minutes}m" if minutes else f"{total_hours}h"
    return f"{minutes}m"


templates.env.globals["format_compact_duration"] = format_compact_duration


templates.env.globals["format_two_unit_duration"] = format_two_unit_duration


def format_storage_bytes(value: int | float | None) -> str:
    try:
        size = float(value or 0)
    except TypeError, ValueError:
        size = 0
    units = ["o", "Ko", "Mo", "Go", "To"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


templates.env.globals["format_storage_bytes"] = format_storage_bytes


def format_video_file_size(value: int | float | None) -> str | None:
    if value is None:
        return None
    try:
        size_mo = float(value) / 1024 / 1024
    except TypeError, ValueError:
        return None
    if size_mo >= 1080:
        return f"{size_mo / 1024:.1f} Go"
    return f"{size_mo:.1f} Mo"


templates.env.globals["format_video_file_size"] = format_video_file_size


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


def format_views(count: int | float | None) -> str | None:
    if count is None:
        return None
    try:
        value = int(count)
    except TypeError, ValueError:
        return None
    return f"{value:,}".replace(",", " ")


def format_subscribers(count: int | float | None) -> str | None:
    formatted = format_views(count)
    if formatted is None:
        return None
    return f"{formatted} abonné{'s' if int(count) > 1 else ''}"


templates.env.globals["format_subscribers"] = format_subscribers


def format_periodicity_rate(value: float) -> str:
    rounded = round(value, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}".replace(".", ",")


def estimate_channel_periodicity(published_at_values: Iterable[datetime | None]) -> str | None:
    dates = sorted({value.date() for value in published_at_values if value}, reverse=True)
    if len(dates) < 2:
        return None
    gaps = sorted(
        max((dates[index] - dates[index + 1]).days, 0.5) for index in range(len(dates) - 1)
    )
    mid = len(gaps) // 2
    median_days = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2
    rate_per_week = 7 / median_days
    if rate_per_week >= 1:
        return f"~{format_periodicity_rate(rate_per_week)}/sem"
    return f"~{format_periodicity_rate(30 / median_days)}/mois"
