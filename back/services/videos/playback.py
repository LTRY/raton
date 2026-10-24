"""Playback activity: recorded as `played` jobs, then read back as positions, screen-time stats, history."""

import json
import math
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, selectinload

from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.durations import (
    format_compact_duration,
    format_duration,
    parse_duration_label,
)
from back.services.common.job_log import log_job
from back.services.videos.filters import video_category_labels, video_list_hide_condition

DASHBOARD_ACTIVITY_STATUSES = {"played", "prompt"}
WATCHED_RATIO = 0.9


PLAYBACK_STATS_KINDS = [
    ("video", "Vidéos"),
    ("short", "Shorts"),
    ("podcast", "Podcasts"),
    ("music", "Musique"),
]


def mark_watched_if_complete(
    video: Video, position_seconds: float, duration_seconds: float, now: datetime | None = None
) -> bool:
    """Mark the fiche Vu (`watched_at`) the first time playback reaches WATCHED_RATIO.

    Does not commit. The date is set once and never moved by playback, so replaying a video
    doesn't postpone the purge of its files. A new download adding a format resets it to
    NULL (see `manual_download`), restarting the countdown.
    """
    if not (math.isfinite(position_seconds) and math.isfinite(duration_seconds)):
        return False
    if video.watched_at is not None or duration_seconds <= 0:
        return False
    if position_seconds / duration_seconds < WATCHED_RATIO:
        return False
    video.watched_at = now or datetime.now(UTC)
    return True


PLAYBACK_MEDIA_TYPES = ("video", "audio")


class InvalidPlaybackMediaError(ValueError):
    pass


def record_playback_activity(
    db: Session,
    video: Video,
    media_type: str,
    position_seconds: float,
    duration_seconds: float,
    watched_seconds: float,
) -> DownloadJob:
    """Record one playback report of the players: the Vu mark, then a `played` job, in one commit.

    The JSON shape of the job is the one `playback_activity_payload_view` reads back.
    """
    if media_type not in PLAYBACK_MEDIA_TYPES:
        raise InvalidPlaybackMediaError("Type de média invalide")
    mark_watched_if_complete(video, position_seconds, duration_seconds)
    position_seconds = max(position_seconds, 0)
    duration_seconds = max(duration_seconds, 0)
    watched_seconds = max(watched_seconds, 0)
    action = "Reprise" if position_seconds >= 3 else "Lecture"
    media_label = "audio" if media_type == "audio" else "vidéo"
    return log_job(
        db,
        "played",
        json.dumps(
            {
                "type": "playback",
                "action": action,
                "media_label": media_label,
                "position_seconds": position_seconds,
                "duration_seconds": duration_seconds,
                "watched_seconds": watched_seconds,
                "title": video.title,
            },
            ensure_ascii=False,
        ),
        channel_id=video.channel_id,
        video_id=video.id,
    )


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


def dashboard_media_activity_logs(
    db: Session,
    limit: int | None = None,
    hide: str = "none",
    no_progress_labels: frozenset[str] = frozenset(),
) -> list[DownloadJob]:
    """Latest activity job of each media, newest first; `hide` leaves out the Vu and/or Écartée
    fiches (`LIST_HIDES`). A job whose fiche was deleted has no state left and always stays."""
    query = (
        select(DownloadJob)
        .where(DownloadJob.status.in_(DASHBOARD_ACTIVITY_STATUSES))
        .order_by(desc(DownloadJob.created_at))
    )
    if hide != "none":
        query = (
            query.outerjoin(Video, Video.id == DownloadJob.video_id)
            .outerjoin(Channel, Channel.id == Video.channel_id)
            .where(
                or_(
                    DownloadJob.video_id.is_(None),
                    video_list_hide_condition(hide, no_progress_labels),
                )
            )
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


def latest_playback_by_video(db: Session, video_ids: list[int]) -> dict[int, dict]:
    """Last playback of each of these fiches, for the progress bar of their cards."""
    latest: dict[int, dict] = {}
    if not video_ids:
        return latest
    jobs = db.scalars(
        select(DownloadJob)
        .where(DownloadJob.status == "played", DownloadJob.video_id.in_(video_ids))
        .order_by(desc(DownloadJob.created_at))
    )
    for job in jobs:
        if job.video_id in latest:
            continue
        playback = playback_activity_view(job)
        if playback:
            latest[job.video_id] = playback
    return latest
