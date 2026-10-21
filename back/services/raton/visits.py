"""Raton's visits: when the person last came, what Raton already said, and the context of a page load."""

import json
import random
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.settings import (
    SCREEN_TIME_KINDS,
    get_screen_time_limits,
    get_setting,
    set_setting,
)
from back.services.raton.picker import pick_next, render_line
from back.services.raton.scenarios import RatonContext
from back.services.videos.filters import followed_video_condition
from back.services.videos.playback import playback_time_stats

RATON_LAST_SEEN_KEY = "raton_last_seen_at"


RATON_SESSION_PREVIOUS_KEY = "raton_session_previous_visit_at"


# JSON list of the lines already shown in the current visit ("<scenario id>:<rank>").
RATON_SHOWN_KEY = "raton_visit_shown"


# A gap this long between two page loads starts a new visit. Without it a
# refresh right after the "long absence" line would already read as "yesterday".
SESSION_GAP = timedelta(minutes=30)


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_shown(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    return [key for key in parsed if isinstance(key, str)] if isinstance(parsed, list) else []


def record_visit(db: Session, now: datetime) -> tuple[datetime | None, list[str]]:
    """Store this page load; return the previous *visit* (not the previous load) and the lines already shown in this visit."""
    last_seen = _parse_datetime(get_setting(db, RATON_LAST_SEEN_KEY, ""))
    new_visit = last_seen is None or now - last_seen >= SESSION_GAP
    if new_visit:
        set_setting(db, RATON_SESSION_PREVIOUS_KEY, last_seen.isoformat() if last_seen else "")
        shown: list[str] = []
        set_setting(db, RATON_SHOWN_KEY, json.dumps(shown))
    else:
        shown = _parse_shown(get_setting(db, RATON_SHOWN_KEY, "[]"))
    previous = _parse_datetime(get_setting(db, RATON_SESSION_PREVIOUS_KEY, ""))
    set_setting(db, RATON_LAST_SEEN_KEY, now.isoformat())
    db.commit()
    return previous, shown


def screen_time_today(db: Session, now: datetime) -> tuple[float, str, float | None, float]:
    """(highest limit ratio, its kind, fewest minutes left over all kinds, total seconds played today)."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    jobs = list(
        db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played")
            .options(selectinload(DownloadJob.video))
            # One day of margin: `playback_time_stats` does the exact local-day cut.
            .where(DownloadJob.created_at >= day_start.replace(tzinfo=None) - timedelta(days=1))
            .order_by(desc(DownloadJob.created_at))
        )
    )
    stats = playback_time_stats(jobs, now)["today"]
    limits = get_screen_time_limits(db)
    best_ratio, best_kind = 0.0, "video"
    minutes_left: float | None = None
    total_seconds = 0.0
    for kind in SCREEN_TIME_KINDS:
        seconds = float(stats[kind]["seconds"])
        total_seconds += seconds
        limit_minutes = limits[kind]["today"]
        ratio = seconds / (limit_minutes * 60)
        if minutes_left is None or ratio > best_ratio:
            best_ratio, best_kind = ratio, kind
        # The closest limit decides the "15 minutes left" warning, not the busiest kind's.
        left = max(limit_minutes - seconds / 60, 0.0)
        minutes_left = left if minutes_left is None else min(minutes_left, left)
    return best_ratio, best_kind, minutes_left, total_seconds


def build_context(db: Session, now: datetime | None = None) -> RatonContext:
    """Facts about the library and the day; no visit bookkeeping, so it is safe to call from a test page."""
    now = now or datetime.now().astimezone()
    ratio, _, minutes_left, played_seconds = screen_time_today(db, now)
    new_count = (
        db.scalar(
            select(func.count(Video.id))
            .join(Channel, Channel.id == Video.channel_id)
            .where(Video.is_new.is_(True))
            .where(followed_video_condition())
        )
        or 0
    )
    return RatonContext(
        now=now,
        limit_ratio=ratio,
        minutes_left=minutes_left,
        played_today_seconds=played_seconds,
        new_count=new_count,
    )


def home_context(
    db: Session, now: datetime | None = None, rng: random.Random | None = None
) -> dict:
    """Template context of the home hero: the line of this page load."""
    ctx = build_context(db, now)
    previous_visit, shown = record_visit(db, ctx.now)
    ctx = replace(ctx, previous_visit=previous_visit)
    scenario, rank, shown = pick_next(ctx, shown, rng)
    set_setting(db, RATON_SHOWN_KEY, json.dumps(shown))
    db.commit()
    return {
        "scenario": render_line(scenario, rank),
    }
