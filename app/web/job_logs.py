"""Helpers of the /logs page: French status badges, filters and day grouping of `download_jobs`."""

from dataclasses import dataclass
from datetime import date, datetime

from app.models.job import DownloadJob
from app.web.shared import format_french_date

LOG_PAGE_SIZE = 50

# Long messages (yt-dlp traces) fold behind "Voir le détail" past this length or on a second line.
LOG_MESSAGE_SUMMARY_LENGTH = 160


@dataclass(frozen=True)
class LogStatus:
    label: str
    family: str  # info, ok, warn, error, neutral: picks the badge colours
    icon: str  # queue, run, ok, warn, error, dot


# Every status written to `download_jobs` (see docs/spec/05-modele-de-donnees.md). An unknown one
# falls back to a neutral badge showing the raw value, so a new status never breaks the page.
LOG_STATUSES = {
    "queued": LogStatus("En file", "info", "queue"),
    "running": LogStatus("En cours", "info", "run"),
    "downloaded": LogStatus("Téléchargé", "ok", "ok"),
    "metadata": LogStatus("Métadonnées", "ok", "ok"),
    "failed": LogStatus("Échec", "error", "error"),
    "cancelled": LogStatus("Arrêté", "neutral", "dot"),
    "warning": LogStatus("Avertissement", "warn", "warn"),
    "skipped": LogStatus("Ignoré", "warn", "warn"),
    "scheduled": LogStatus("Programmée", "neutral", "dot"),
    "purged": LogStatus("Purgé", "neutral", "dot"),
    "played": LogStatus("Lecture", "neutral", "dot"),
    "prompt": LogStatus("Question IA", "neutral", "dot"),
}

# Filter key -> (label, statuses it keeps; None keeps everything).
LOG_FILTERS: dict[str, tuple[str, frozenset[str] | None]] = {
    "all": ("Tout", None),
    "errors": ("Erreurs", frozenset({"failed"})),
    "warnings": ("Avertissements", frozenset({"warning", "skipped"})),
    "running": ("En cours", frozenset({"queued", "running"})),
}


def log_status(status: str) -> LogStatus:
    return LOG_STATUSES.get(status) or LogStatus(status, "neutral", "dot")


def normalize_log_filter(value: str | None) -> str:
    return value if value in LOG_FILTERS else "all"


def split_log_message(message: str) -> tuple[str, str | None]:
    """Return the one-line summary of a message and, when it is longer, the full text."""
    text = message.strip()
    first_line = text.splitlines()[0] if text else ""
    if len(first_line) > LOG_MESSAGE_SUMMARY_LENGTH:
        return first_line[: LOG_MESSAGE_SUMMARY_LENGTH - 1].rstrip() + "…", text
    if "\n" in text:
        return first_line, text
    return text, None


def log_day_label(day: date, today: date) -> str:
    delta = (today - day).days
    if delta == 0:
        return "Aujourd’hui"
    if delta == 1:
        return "Hier"
    return format_french_date(datetime.combine(day, datetime.min.time()))


def log_row(job: DownloadJob) -> dict:
    summary, detail = split_log_message(job.message)
    # A video's own title leads; a job with no video (scan, import) is named after its channel.
    if job.video:
        title, href = job.video.title, f"/videos/{job.video.id}"
        sub = job.channel.name if job.channel else ""
    elif job.channel:
        title, href, sub = job.channel.name, f"/videos?channel_id={job.channel.id}", ""
    else:
        title, href, sub = "Tâche système", None, ""
    return {
        "time": f"{job.created_at:%H:%M}",
        "status": job.status,
        "badge": log_status(job.status),
        "title": title,
        "href": href,
        "sub": sub,
        "message": summary,
        "detail": detail,
    }


def log_days(jobs: list[DownloadJob], today: date) -> list[dict]:
    """Group jobs (newest first) by calendar day, each group labelled Aujourd'hui, Hier or its date."""
    days: list[dict] = []
    for job in jobs:
        day = job.created_at.date()
        if not days or days[-1]["date"] != day:
            days.append({"date": day, "label": log_day_label(day, today), "rows": []})
        days[-1]["rows"].append(log_row(job))
    return days
