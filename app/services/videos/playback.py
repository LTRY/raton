"""Playback activity read back from the `played` jobs: positions, screen-time stats, history."""

import json
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models.job import DownloadJob
from app.services.durations import format_compact_duration, format_duration, parse_duration_label
from app.services.videos.filters import video_category_labels

DASHBOARD_ACTIVITY_STATUSES = {"played", "prompt"}


PLAYBACK_STATS_KINDS = [
    ("video", "Vidéos"),
    ("short", "Shorts"),
    ("podcast", "Podcasts"),
    ("music", "Musique"),
]


def legacy_playback_activity_view(message: str) -> dict[str, str | float] | None:
    match = re.match(
        r"^(?P<action>Lecture|Reprise) (?P<media_label>audio|vidéo)"
        r"(?: pendant (?P<watched_label>\d+:\d{2}(?::\d{2})?))?"
        r" à (?P<position_label>\d+:\d{2}(?::\d{2})?):(?P<title>.*)",
        message,
    )
    if not match:
        return None
    position_seconds = parse_duration_label(match.group("position_label"))
    if position_seconds is None:
        return None
    watched_seconds = parse_duration_label(match.group("watched_label")) or 0
    return playback_activity_payload_view(
        match.group("action"),
        match.group("media_label"),
        position_seconds,
        position_seconds,
        watched_seconds,
        False,
        title=match.group("title"),
    )


def playback_activity_payload_view(
    action: str,
    media_label: str,
    position_seconds: float,
    duration_seconds: float,
    watched_seconds: float,
    is_completed: bool | None = None,
    title: str = "",
) -> dict[str, str | float]:
    progress_percent = 0
    if duration_seconds > 0:
        progress_percent = min((position_seconds / duration_seconds) * 100, 100)
    if is_completed is None:
        is_completed = (
            duration_seconds > 0
            and progress_percent >= 95
            and duration_seconds - position_seconds <= 5
        )
    return {
        "action": action,
        "media_label": media_label,
        # Recorded at playback time: the only name left once the video row is deleted.
        "title": title.strip(),
        "position_label": format_duration(position_seconds) or "0:00",
        "duration_label": format_duration(duration_seconds) or "0:00",
        "watched_label": format_duration(watched_seconds) or "0:00",
        "watched_seconds": watched_seconds,
        "position_seconds": position_seconds,
        "duration_seconds": duration_seconds,
        "progress_percent": round(progress_percent, 2),
        "is_completed": is_completed,
    }


def playback_activity_view(job: DownloadJob) -> dict[str, str | float] | None:
    if job.status != "played":
        return None
    try:
        payload = json.loads(job.message)
    except TypeError, json.JSONDecodeError:
        return legacy_playback_activity_view(job.message)
    if not isinstance(payload, dict) or payload.get("type") != "playback":
        return legacy_playback_activity_view(job.message)
    try:
        position_seconds = max(float(payload.get("position_seconds", 0)), 0)
        duration_seconds = max(float(payload.get("duration_seconds", 0)), 0)
        watched_seconds = max(float(payload.get("watched_seconds", 0)), 0)
    except TypeError, ValueError:
        return None
    return playback_activity_payload_view(
        str(payload.get("action") or "Lecture"),
        str(payload.get("media_label") or "vidéo"),
        position_seconds,
        duration_seconds,
        watched_seconds,
        title=str(payload.get("title") or ""),
    )


def latest_playback_positions(db: Session, video_id: int) -> dict[str, dict[str, float | int]]:
    """Dernière position de lecture connue du serveur, par type de média.

    Sert de repli à la reprise côté client : la position vit d'abord dans le
    `localStorage` du navigateur, qui est propre à chaque appareil et que Safari
    iOS purge après 7 jours sans visite. `at_ms` permet au client de départager
    sa copie locale et celle du serveur (la plus récente gagne).
    """
    positions: dict[str, dict[str, float | int]] = {}
    jobs = db.scalars(
        select(DownloadJob)
        .where(DownloadJob.status == "played", DownloadJob.video_id == video_id)
        .order_by(desc(DownloadJob.created_at), desc(DownloadJob.id))
    )
    for job in jobs:
        try:
            payload = json.loads(job.message)
            position_seconds = max(float(payload["position_seconds"]), 0)
        except TypeError, ValueError, KeyError, json.JSONDecodeError:
            continue
        if payload.get("type") != "playback":
            continue
        kind = "audio" if payload.get("media_label") == "audio" else "video"
        if kind in positions:
            continue
        created_at = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=UTC)
        positions[kind] = {
            "position_seconds": position_seconds,
            "at_ms": int(created_at.timestamp() * 1000),
        }
        if len(positions) == 2:
            break
    return positions


def local_datetime(value: datetime, timezone) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def playback_stats_kind(job: DownloadJob, playback: dict[str, str | float]) -> str:
    if playback["media_label"] == "vidéo":
        if job.video and "/shorts/" in job.video.url:
            return "short"
        return "video"
    labels = set(video_category_labels(job.video)) if job.video else set()
    if labels.intersection({"podcast", "podcasts"}):
        return "podcast"
    if labels.intersection({"music", "musique"}):
        return "music"
    return "music"


def playback_stats_periods(now: datetime) -> dict[str, datetime]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": today,
        "week": today - timedelta(days=6),
        "month": today - timedelta(days=29),
    }


def empty_playback_stats() -> dict[str, dict[str, dict[str, str | float]]]:
    return {
        period: {
            kind: {"label": label, "seconds": 0.0, "duration": "0:00", "count": 0}
            for kind, label in PLAYBACK_STATS_KINDS
        }
        for period in ("today", "week", "month")
    }


def recent_played_jobs(db: Session, now: datetime | None = None) -> list[DownloadJob]:
    """ "played" jobs that can still count in `playback_time_stats`, with their video loaded in one query.

    `playback_stats_kind` reads `job.video` for every job, so a lazy load there costs one statement per
    video, and the table grows with every playback. The longest period is 30 days; two days of margin
    absorb the naive-vs-local timezone cut, which `playback_time_stats` redoes exactly.
    """
    now = now or datetime.now().astimezone()
    month_start = playback_stats_periods(now)["month"]
    cutoff = month_start.replace(tzinfo=None) - timedelta(days=2)
    return list(
        db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played", DownloadJob.created_at >= cutoff)
            .options(selectinload(DownloadJob.video))
            .order_by(desc(DownloadJob.created_at))
        )
    )


def playback_time_stats(
    jobs: list[DownloadJob], now: datetime | None = None
) -> dict[str, dict[str, dict[str, str | float]]]:
    now = now or datetime.now().astimezone()
    periods = playback_stats_periods(now)
    stats = empty_playback_stats()
    seen_media_keys = {
        period: {kind: set() for kind, _ in PLAYBACK_STATS_KINDS} for period in periods
    }
    for job in jobs:
        playback = playback_activity_view(job)
        if not playback:
            continue
        created_at = local_datetime(job.created_at, now.tzinfo)
        kind = playback_stats_kind(job, playback)
        media_key = job.video_id or job.id
        watched_seconds = float(playback["watched_seconds"])
        for period, starts_at in periods.items():
            if created_at >= starts_at:
                stats[period][kind]["seconds"] = (
                    float(stats[period][kind]["seconds"]) + watched_seconds
                )
                if media_key not in seen_media_keys[period][kind]:
                    seen_media_keys[period][kind].add(media_key)
                    stats[period][kind]["count"] = int(stats[period][kind]["count"]) + 1
    for period_stats in stats.values():
        for item in period_stats.values():
            item["duration"] = format_compact_duration(item["seconds"])
    return stats


def playback_seconds_by_day(
    jobs: list[DownloadJob], now: datetime | None = None
) -> dict[date, float]:
    """Seconds watched per local day, over every "played" job (not just the latest per media)."""
    now = now or datetime.now().astimezone()
    seconds_by_day: dict[date, float] = {}
    for job in jobs:
        playback = playback_activity_view(job)
        if not playback:
            continue
        day = local_datetime(job.created_at, now.tzinfo).date()
        seconds_by_day[day] = seconds_by_day.get(day, 0.0) + float(playback["watched_seconds"])
    return seconds_by_day


def dashboard_media_activity_logs(db: Session, limit: int | None = None) -> list[DownloadJob]:
    query = (
        select(DownloadJob)
        .where(DownloadJob.status.in_(DASHBOARD_ACTIVITY_STATUSES))
        .order_by(desc(DownloadJob.created_at))
    )
    if limit is not None:
        query = query.limit(limit)
    media_activity_logs = []
    seen_media_keys = set()
    for job in db.scalars(query):
        playback = playback_activity_view(job)
        if not playback:
            continue
        if job.video_id:
            media_key = ("video", job.video_id)
        elif playback["title"]:
            # The video row is gone (`video_id` is SET NULL on delete): its activity
            # jobs can only be told apart from another video's by the recorded title.
            media_key = ("title", job.channel_id, playback["title"])
        else:
            media_key = ("job", job.id)
        if media_key in seen_media_keys:
            continue
        seen_media_keys.add(media_key)
        media_activity_logs.append(job)
    return media_activity_logs
