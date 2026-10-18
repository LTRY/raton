from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.channels import followed_video_condition
from app.services.settings import (
    get_llm_provider_display_label,
    get_no_progress_category_labels,
    get_screen_time_limits,
    get_video_category_label_styles,
)
from app.web.playback import (
    dashboard_media_activity_logs,
    history_day_groups,
    playback_seconds_by_day,
    playback_time_dashboard,
    playback_time_stats,
    recent_played_jobs,
)
from app.web.raton import home_context as raton_home_context
from app.web.routes.library_chat import library_chat_payload, library_chat_scope_config
from app.web.shared import (
    category_style_map,
    current_request_path,
    page_href_builder,
    paginate,
    templates,
)
from app.web.video_library import downloaded_video_card

router = APIRouter()


NOUVEAUTES_CHANNEL_PAGE_SIZE = 10
NOUVEAUTES_STACK_SIZE = 10


def dashboard_new_video_stacks(
    db: Session, page: int = 1, page_size: int = NOUVEAUTES_CHANNEL_PAGE_SIZE
) -> tuple[list[dict], int, int]:
    """Nouveautés: one stack of the most recent videos per followed channel, paginated by channel.

    Already-visited videos stay listed (this is not a filter on `Video.is_new`);
    only the per-channel pagination limits what is shown. Each bell scopes its
    own kind: a video is listed only when the bell matching its kind (video or
    short) is on for its channel. Videos imported through a playlist land on a
    channel with no bell and must never feed this section (see
    docs/spec/07-youtube-et-telechargements.md).
    """
    recency = func.coalesce(Video.published_at, Video.downloaded_at, Video.created_at)
    followed_kind = followed_video_condition()
    channel_ids = list(
        db.scalars(
            select(Video.channel_id)
            .join(Channel, Channel.id == Video.channel_id)
            .where(followed_kind)
            .group_by(Video.channel_id)
            .order_by(desc(func.max(recency)))
        )
    )
    channel_ids, page, total_pages = paginate(channel_ids, page, page_size)

    stacks = []
    for channel_id in channel_ids:
        channel = db.get(Channel, channel_id)
        if channel is None:
            continue
        channel_videos = list(
            db.scalars(
                select(Video)
                .join(Channel, Channel.id == Video.channel_id)
                .where(Video.channel_id == channel_id)
                .where(followed_kind)
                .order_by(
                    desc(Video.published_at), desc(Video.downloaded_at), desc(Video.created_at)
                )
                .limit(NOUVEAUTES_STACK_SIZE)
            )
        )
        if not channel_videos:
            continue
        stacks.append(
            {
                "channel": channel,
                "video_cards": [downloaded_video_card(video) for video in channel_videos],
            }
        )
    return stacks, page, total_pages


def dashboard_context(db: Session) -> dict:
    """Home renders Raton's scenario and the library chat bar, nothing else."""
    return {
        "raton": raton_home_context(db),
        "chat_widget_config": {
            "defaultScope": "library",
            "llmProviderLabel": get_llm_provider_display_label(),
            "scopes": {"library": library_chat_scope_config(library_chat_payload(db))},
        },
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        dashboard_context(db),
    )


@router.get("/dashboard/nouveautes", response_class=HTMLResponse)
def dashboard_new_videos_page(request: Request, page: int = 1, db: Session = Depends(get_db)):
    page = max(page, 1)
    video_stacks, page, total_pages = dashboard_new_video_stacks(db, page=page)
    category_label_styles = get_video_category_label_styles(db)
    return templates.TemplateResponse(
        request,
        "dashboard_new_videos.html",
        {
            "video_stacks": video_stacks,
            "current_new_videos_path": current_request_path(request),
            "category_style_map": category_style_map(category_label_styles),
            "no_progress_categories": get_no_progress_category_labels(db),
            "page": page,
            "total_pages": total_pages,
            "page_href": page_href_builder(request),
        },
    )


@router.get("/dashboard/reprises", response_class=HTMLResponse)
def dashboard_resume_page_redirect(request: Request):
    """Ancienne URL de la page, renommee avec la section "A reprendre" -> "Historique".

    Redirection temporaire (302) plutot que permanente : un 301 resterait en cache du
    navigateur meme si l'URL rebougeait, ce qui n'apporte rien sur une app de LAN.
    """
    query = request.url.query
    return RedirectResponse(f"/dashboard/historique{'?' + query if query else ''}", status_code=302)


@router.get("/dashboard/historique", response_class=HTMLResponse)
def dashboard_history_page(request: Request, page: int = 1, db: Session = Depends(get_db)):
    page = max(page, 1)
    media_activity_logs = dashboard_media_activity_logs(db)
    media_activity_logs, page, total_pages = paginate(media_activity_logs, page)
    category_label_styles = get_video_category_label_styles(db)
    # Reading time counts every playback, while the list below keeps one row per media.
    played_jobs = list(
        db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played")
            .order_by(desc(DownloadJob.created_at))
        )
    )
    now = datetime.now().astimezone()
    return templates.TemplateResponse(
        request,
        "dashboard_history.html",
        {
            "history_days": history_day_groups(
                media_activity_logs, now, playback_seconds_by_day(played_jobs, now)
            ),
            "playback_time_stats": playback_time_dashboard(
                playback_time_stats(recent_played_jobs(db, now), now), get_screen_time_limits(db)
            ),
            "category_style_map": category_style_map(category_label_styles),
            "no_progress_categories": get_no_progress_category_labels(db),
            "page": page,
            "total_pages": total_pages,
            "page_href": page_href_builder(request),
        },
    )
