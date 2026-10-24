"""What the cards and rows of the lists show, from the API's raw values."""

from datetime import date, datetime

from front.formatting import format_compact_duration, format_duration, format_french_date

BADGE_TEXTS = {
    "new": "Nouveau",
    "audio": "Audio",
    "video": "Vidéo",
    "metadata": "Métadonnées",
    "transcript": "Transcript",
    "notes": "Notes",
    "imported": "Manuelle",
}


def badge_labels(kinds: list[str]) -> list[dict[str, str]]:
    return [{"text": BADGE_TEXTS[kind], "kind": kind} for kind in kinds]


def playback_view(playback):
    """Adds the `m:ss` labels a progress bar reads."""
    if playback is not None:
        playback.position_label = format_duration(playback.position_seconds) or "0:00"
        playback.duration_label = format_duration(playback.duration_seconds) or "0:00"
    return playback


def card_view(card):
    card.duration = format_duration(card.duration_seconds)
    playback_view(card.playback)
    return card


def card_views(cards: list) -> list:
    return [card_view(card) for card in cards]


def day_label(day: date, today: date) -> str:
    elapsed_days = (today - day).days
    if elapsed_days == 0:
        return "Aujourd’hui"
    if elapsed_days == 1:
        return "Hier"
    return format_french_date(day)


def history_days(rows: list, day_seconds, today: date) -> list[dict]:
    """The Historique rows (newest first) under one heading per local day."""
    days: list[dict] = []
    for row in rows:
        playback_view(row.playback)
        row.watched_label = format_duration(getattr(row, "watched_seconds", 0))
        if not days or days[-1]["key"] != row.day:
            day = date.fromisoformat(row.day)
            days.append(
                {
                    "key": row.day,
                    "label": day_label(day, today),
                    "full_label": format_french_date(day),
                    "seconds": day_seconds.get(row.day, 0.0),
                    "rows": [],
                }
            )
        days[-1]["rows"].append(row)
    return days


def screen_time_rings(screen_time) -> dict:
    """Each ring of the reading time: its fill against the limit, green to red as it fills."""
    rings = {}
    for period, kinds in vars(screen_time.periods).items():
        rings[period] = {}
        for kind, item in vars(kinds).items():
            limit_seconds = max(item.limit_minutes * 60, 1)
            ratio = min(float(item.seconds) / limit_seconds, 1)
            hue = round(120 * (1 - ratio))
            rings[period][kind] = {
                "seconds": item.seconds,
                "limit": format_compact_duration(limit_seconds),
                "percent": round(ratio * 100),
                "color": f"hsl({hue} 72% 42%)",
            }
    return rings


def local_today() -> date:
    return datetime.now().astimezone().date()
