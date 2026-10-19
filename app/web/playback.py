from datetime import date, datetime

from app.models.job import DownloadJob
from app.services.common.durations import format_compact_duration
from app.services.videos.playback import local_datetime, playback_activity_view
from app.web.shared import format_french_date, templates

templates.env.globals["playback_activity_view"] = playback_activity_view


def playback_time_dashboard(stats: dict, limits: dict[str, dict[str, int]]) -> dict:
    for period, period_stats in stats.items():
        for kind, item in period_stats.items():
            limit_seconds = max(limits[kind][period] * 60, 1)
            ratio = min(float(item["seconds"]) / limit_seconds, 1)
            hue = round(120 * (1 - ratio))
            item.update(
                {
                    "limit": format_compact_duration(limit_seconds),
                    "percent": round(ratio * 100),
                    "color": f"hsl({hue} 72% 42%)",
                }
            )
    return stats


def history_day_groups(
    jobs: list[DownloadJob],
    now: datetime | None = None,
    seconds_by_day: dict[date, float] | None = None,
) -> list[dict]:
    """Group the "Historique" jobs by local day of playback, most recent day first.

    `jobs` arrives already sorted by `created_at` descending (see
    `dashboard_media_activity_logs`), so appending in order keeps both the days and the
    medias inside each day in that same order. The local timezone is resolved the same way
    as `playback_time_stats`, so a media counted in "Aujourd'hui" by the screen-time rings
    lands in the "Aujourd'hui" group here too.

    `jobs` holds one job per media, so a day's reading time comes from `seconds_by_day`
    (see `playback_seconds_by_day`), which counts every playback of the day.
    """
    now = now or datetime.now().astimezone()
    today = now.date()
    groups: list[dict] = []
    groups_by_day: dict[date, dict] = {}
    for job in jobs:
        created_at = local_datetime(job.created_at, now.tzinfo)
        day = created_at.date()
        group = groups_by_day.get(day)
        if group is None:
            full_label = format_french_date(created_at)
            elapsed_days = (today - day).days
            if elapsed_days == 0:
                label = "Aujourd’hui"
            elif elapsed_days == 1:
                label = "Hier"
            else:
                label = full_label
            group = {
                "day": day,
                "label": label,
                "full_label": full_label,
                "seconds": (seconds_by_day or {}).get(day, 0.0),
                "jobs": [],
            }
            groups_by_day[day] = group
            groups.append(group)
        group["jobs"].append(job)
    return groups
