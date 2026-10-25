"""How values read: dates, durations, sizes, counts and category colours, in French.

Display only: the API returns raw values (seconds, bytes, ISO dates, `#rrggbb`) and the
templates format them with these helpers (`front/templating.py` registers them).
"""

from datetime import datetime

FRENCH_WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
FRENCH_MONTHS_ABBR = [
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
]


def format_french_date(value: datetime) -> str:
    return f"{FRENCH_WEEKDAYS[value.weekday()]}. {value.day:02d} {FRENCH_MONTHS_ABBR[value.month - 1]} {value.year}"


def format_relative_age(value: datetime, now: datetime | None = None) -> str:
    """« il y a 3 ans »: for a date that is only known roughly, as YouTube's search gives it."""
    days = max(((now or datetime.now(value.tzinfo)) - value).days, 0)
    if days == 0:
        return "aujourd’hui"
    for unit_days, singular, plural in (
        (365, "an", "ans"),
        (30, "mois", "mois"),
        (7, "semaine", "semaines"),
        (1, "jour", "jours"),
    ):
        if days >= unit_days:
            count = days // unit_days
            return f"il y a {count} {singular if count == 1 else plural}"
    return "aujourd’hui"


def format_french_datetime(value: datetime) -> str:
    return f"{format_french_date(value)} {value:%H:%M}"


def format_duration(seconds: int | float | None) -> str | None:
    """`m:ss` or `h:mm:ss`; None for no duration."""
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


def format_periodicity_rate(value: float) -> str:
    rounded = round(value, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}".replace(".", ",")


def category_text_color(color: str) -> str:
    red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    return "#0f172a" if brightness > 150 else "#ffffff"


def video_category_css_style(label_style) -> str:
    """CSS variables of a category chip; the API gives normalized `#rrggbb` colours."""
    color = label_style.get("color") or "#16a34a"
    return f"--category-bg: {color}; --category-border: {color}; --category-text: {category_text_color(color)};"


def category_style_map(label_styles: list) -> dict:
    return {style["label"]: style for style in label_styles}
