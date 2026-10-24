"""The Historique of a user: one row per media and per local day, newest first.

Days are cut in the server's local timezone, like the screen-time totals of
`playback_time_stats`, so a media counted in "Aujourd'hui" by the rings sits in the
"Aujourd'hui" group of the list too.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from back.models.job import DownloadJob
from back.models.user import UserVideo
from back.services.common.settings import get_no_progress_category_labels
from back.services.common.user_state import video_states
from back.services.videos.list_state import card_list_states, video_auto_list_state
from back.services.videos.playback import (
    local_datetime,
    playback_activity_view,
    playback_media_key,
)

HISTORY_PAGE_SIZE = 50


@dataclass
class HistoryRow:
    # The day's latest playback report of the media: its position is the row's progress bar.
    job: DownloadJob
    day: date
    # The user's state on the fiche; None once the fiche is gone.
    state: UserVideo | None
    playback: dict
    shown_state: str
    auto_state: str
    replay_category: bool
    # Every report of the media that day added up: a replay counts again.
    watched_seconds: float = 0.0
    # The fiche was already Vu before that day.
    rewatch: bool = False


@dataclass
class HistoryPage:
    rows: list[HistoryRow]
    page: int
    total_pages: int
    # Reading time of each day of the page, over every playback of the day.
    seconds_by_day: dict[date, float] = field(default_factory=dict)


@dataclass
class _DayEntry:
    job_id: int
    day: date
    watched_seconds: float = 0.0


def _day_entries(
    db: Session, user_id: int, now: datetime
) -> tuple[list[_DayEntry], dict[date, float]]:
    """The user's playbacks grouped by (media, local day), newest first, and each day's total.

    Each report of a player only holds the seconds watched since the previous one, so a row
    and a day add up all their reports.
    """
    entries: dict[tuple, _DayEntry] = {}
    seconds_by_day: dict[date, float] = {}
    jobs = db.scalars(
        select(DownloadJob)
        .where(DownloadJob.status == "played", DownloadJob.user_id == user_id)
        .order_by(desc(DownloadJob.created_at), desc(DownloadJob.id))
    )
    for job in jobs:
        playback = playback_activity_view(job)
        if not playback:
            continue
        day = local_datetime(job.created_at, now.tzinfo).date()
        watched = float(playback["watched_seconds"])
        seconds_by_day[day] = seconds_by_day.get(day, 0.0) + watched
        key = (playback_media_key(job, playback), day)
        entry = entries.get(key)
        if entry is None:
            entry = entries[key] = _DayEntry(job_id=job.id, day=day)
        entry.watched_seconds += watched
    return list(entries.values()), seconds_by_day


def history_page(
    db: Session,
    user_id: int,
    page: int = 1,
    now: datetime | None = None,
    page_size: int = HISTORY_PAGE_SIZE,
) -> HistoryPage:
    now = now or datetime.now().astimezone()
    entries, all_seconds_by_day = _day_entries(db, user_id, now)
    total_pages = max(1, -(-len(entries) // page_size))
    page = min(max(page, 1), total_pages)
    page_entries = entries[(page - 1) * page_size : page * page_size]
    # The fiche and channel of each row of the page in two queries, not two per row.
    loaded = {
        job.id: job
        for job in db.scalars(
            select(DownloadJob)
            .where(DownloadJob.id.in_([entry.job_id for entry in page_entries]))
            .options(selectinload(DownloadJob.video), selectinload(DownloadJob.channel))
        )
    }
    no_progress_labels = set(get_no_progress_category_labels(db))
    states = video_states(db, user_id, [job.video_id for job in loaded.values() if job.video_id])
    rows = []
    for entry in page_entries:
        job = loaded[entry.job_id]
        playback = playback_activity_view(job)
        state = states[job.video_id] if job.video else None
        rewatch = False
        if job.video:
            shown, auto, replay = card_list_states(job.video, state, playback, no_progress_labels)
            rewatch = (
                not replay
                and state.watched_at is not None
                and local_datetime(state.watched_at, now.tzinfo).date() < entry.day
            )
        else:
            # The fiche is gone: only what the playback itself says.
            replay = False
            shown = auto = video_auto_list_state(playback, replay)
        rows.append(
            HistoryRow(
                job=job,
                day=entry.day,
                state=state,
                playback=playback,
                shown_state=shown,
                auto_state=auto,
                replay_category=replay,
                watched_seconds=entry.watched_seconds,
                rewatch=rewatch,
            )
        )
    days = {row.day for row in rows}
    seconds_by_day = {day: seconds for day, seconds in all_seconds_by_day.items() if day in days}
    return HistoryPage(rows=rows, page=page, total_pages=total_pages, seconds_by_day=seconds_by_day)
