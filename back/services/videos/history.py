"""The Historique: the latest playback of each media, newest first, grouped by local day.

Days are cut in the server's local timezone, like the screen-time totals of
`playback_time_stats`, so a media counted in "Aujourd'hui" by the rings sits in the
"Aujourd'hui" group of the list too.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from back.models.job import DownloadJob
from back.services.common.settings import get_no_progress_category_labels
from back.services.videos.list_state import card_list_states, video_auto_list_state
from back.services.videos.playback import (
    dashboard_media_activity_logs,
    local_datetime,
    playback_activity_view,
    playback_seconds_by_day,
)

HISTORY_PAGE_SIZE = 50


@dataclass
class HistoryRow:
    job: DownloadJob
    day: date
    playback: dict
    shown_state: str
    auto_state: str
    replay_category: bool


@dataclass
class HistoryPage:
    rows: list[HistoryRow]
    page: int
    total_pages: int
    # Reading time of each day of the page, over every playback of the day (not one per media).
    seconds_by_day: dict[date, float] = field(default_factory=dict)


def history_page(
    db: Session, page: int = 1, now: datetime | None = None, page_size: int = HISTORY_PAGE_SIZE
) -> HistoryPage:
    now = now or datetime.now().astimezone()
    jobs = dashboard_media_activity_logs(db)
    total_pages = max(1, -(-len(jobs) // page_size))
    page = min(max(page, 1), total_pages)
    page_ids = [job.id for job in jobs[(page - 1) * page_size : page * page_size]]
    # The fiche and channel of each row of the page in two queries, not two per row.
    loaded = {
        job.id: job
        for job in db.scalars(
            select(DownloadJob)
            .where(DownloadJob.id.in_(page_ids))
            .options(selectinload(DownloadJob.video), selectinload(DownloadJob.channel))
        )
    }
    no_progress_labels = set(get_no_progress_category_labels(db))
    rows = []
    for job_id in page_ids:
        job = loaded[job_id]
        playback = playback_activity_view(job)
        if job.video:
            shown, auto, replay = card_list_states(job.video, playback, no_progress_labels)
        else:
            # The fiche is gone: only what the playback itself says.
            replay = False
            shown = auto = video_auto_list_state(playback, replay)
        rows.append(
            HistoryRow(
                job=job,
                day=local_datetime(job.created_at, now.tzinfo).date(),
                playback=playback,
                shown_state=shown,
                auto_state=auto,
                replay_category=replay,
            )
        )
    seconds_by_day: dict[date, float] = {}
    if rows:
        # Only the days of the page: a day's every playback, not a scan of the whole table.
        first = min(row.day for row in rows)
        start = datetime.combine(first, datetime.min.time()) - timedelta(days=1)
        played = list(
            db.scalars(
                select(DownloadJob).where(
                    DownloadJob.status == "played", DownloadJob.created_at >= start
                )
            )
        )
        days = {row.day for row in rows}
        seconds_by_day = {
            day: seconds
            for day, seconds in playback_seconds_by_day(played, now).items()
            if day in days
        }
    return HistoryPage(rows=rows, page=page, total_pages=total_pages, seconds_by_day=seconds_by_day)
