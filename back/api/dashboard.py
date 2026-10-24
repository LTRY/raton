"""`/api/nouveautes`, `/api/historique`, `/api/screen-time`: what the Dashboard pages show."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from back.api.cards import card_reads
from back.api.errors import error_responses
from back.db.session import get_db
from back.schemas.dashboard import (
    HistoriqueRead,
    HistoryRowRead,
    HistoryVideoRead,
    NouveautesRead,
    NouveautesStackRead,
    PlaybackRead,
    ScreenTimeItemRead,
    ScreenTimeRead,
)
from back.schemas.library import LibraryChannelRead
from back.services.common.settings import get_screen_time_limits
from back.services.videos.filters import video_badges
from back.services.videos.history import history_page
from back.services.videos.nouveautes import nouveautes_stacks
from back.services.videos.playback import playback_time_stats, recent_played_jobs

router = APIRouter(prefix="/api", tags=["Tableau de bord"])


@router.get("/nouveautes", response_model=NouveautesRead, responses=error_responses(422))
def get_nouveautes(
    page: int = Query(1, ge=1), show_hidden: bool = False, db: Session = Depends(get_db)
) -> NouveautesRead:
    stacks, page, total_pages = nouveautes_stacks(db, page, show_hidden=show_hidden)
    return NouveautesRead(
        stacks=[
            NouveautesStackRead(
                channel=LibraryChannelRead(id=channel.id, name=channel.name),
                items=card_reads(db, videos),
            )
            for channel, videos in stacks
        ],
        page=page,
        total_pages=total_pages,
    )


@router.get("/historique", response_model=HistoriqueRead, responses=error_responses(422))
def get_historique(
    page: int = Query(1, ge=1), show_hidden: bool = False, db: Session = Depends(get_db)
) -> HistoriqueRead:
    history = history_page(db, page, show_hidden=show_hidden)
    rows = []
    for row in history.rows:
        video, channel = row.job.video, row.job.channel
        rows.append(
            HistoryRowRead(
                job_id=row.job.id,
                created_at=row.job.created_at,
                day=row.day,
                video=HistoryVideoRead(
                    id=video.id,
                    title=video.title,
                    rating=video.rating,
                    file_size_bytes=video.file_size_bytes,
                    list_state=video.list_state,
                    categories=video.category_labels,
                    badges=video_badges(video),
                )
                if video
                else None,
                channel=LibraryChannelRead(id=channel.id, name=channel.name) if channel else None,
                playback=PlaybackRead(**row.playback),
                shown_state=row.shown_state,
                auto_state=row.auto_state,
                replay_category=row.replay_category,
            )
        )
    return HistoriqueRead(
        rows=rows,
        page=history.page,
        total_pages=history.total_pages,
        day_seconds=history.seconds_by_day,
    )


@router.get("/screen-time", response_model=ScreenTimeRead)
def get_screen_time(db: Session = Depends(get_db)) -> ScreenTimeRead:
    now = datetime.now().astimezone()
    stats = playback_time_stats(recent_played_jobs(db, now), now)
    limits = get_screen_time_limits(db)
    return ScreenTimeRead(
        periods={
            period: {
                kind: ScreenTimeItemRead(
                    seconds=item["seconds"], count=item["count"], limit_minutes=limits[kind][period]
                )
                for kind, item in kinds.items()
            }
            for period, kinds in stats.items()
        }
    )
