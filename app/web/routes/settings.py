from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.db.session import get_db
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.common.categories import (
    parse_video_category_label_styles,
    parse_video_category_labels,
    serialize_video_category_labels,
)
from app.services.common.library_views import (
    parse_video_library_views,
)
from app.services.common.settings import (
    DEFAULT_VIDEO_CATEGORY_LABELS,
    SPONSOR_SEGMENT_CATEGORY_CHOICES,
    SPONSOR_SEGMENT_CATEGORY_LABELS,
    get_auto_notes_enabled,
    get_auto_notes_excluded_category_labels,
    get_global_quota_bytes,
    get_media_root,
    get_no_progress_category_labels,
    get_screen_time_limits,
    get_setting,
    get_sponsor_segment_categories,
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
    get_video_category_labels,
    get_video_library_views,
    save_settings,
)
from app.services.ingest import scan_events
from app.services.ingest.scanner import scan_lock
from app.services.jobs.scheduler import get_last_auto_scan_info
from app.services.llm.usage import llm_usage_summary
from app.services.rag.auto_notes import LAST_RUN_AT_KEY as AUTO_NOTES_LAST_RUN_AT_KEY
from app.services.rag.auto_notes import LAST_RUN_SUMMARY_KEY as AUTO_NOTES_LAST_RUN_SUMMARY_KEY
from app.web.job_logs import LOG_FILTERS, LOG_PAGE_SIZE, log_days, normalize_log_filter
from app.web.library_stats import library_stats_context
from app.web.shared import form_list_values, form_text_value, page_href_builder, redirect, templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    video_category_labels = get_video_category_labels(db)
    video_category_label_styles = get_video_category_label_styles(db)
    video_library_views = get_video_library_views(db)
    screen_time_limits = get_screen_time_limits(db)
    no_progress_categories = get_no_progress_category_labels(db)
    known_category_labels = {style["label"] for style in video_category_label_styles}
    no_progress_category_options = video_category_label_styles + [
        {"label": label, "color": None}
        for label in no_progress_categories
        if label not in known_category_labels
    ]
    auto_notes_excluded = get_auto_notes_excluded_category_labels(db)
    auto_notes_category_options = video_category_label_styles + [
        {"label": label, "color": None}
        for label in auto_notes_excluded
        if label not in known_category_labels
    ]
    last_run_at = get_setting(db, AUTO_NOTES_LAST_RUN_AT_KEY, "")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            **library_stats_context(db),
            "media_root": get_media_root(db),
            "quota_gb": round(get_global_quota_bytes(db) / 1024 / 1024 / 1024, 2),
            "llm_usage": llm_usage_summary(db),
            "last_auto_scan": get_last_auto_scan_info(db),
            "scan_running": scan_lock.locked(),
            "scan_events_last_id": scan_events.events_after(0)[1],
            "video_category_labels": "\n".join(video_category_labels),
            "video_category_labels_list": video_category_labels,
            "video_category_label_styles": video_category_label_styles,
            "video_library_views": video_library_views,
            "screen_time_limits": screen_time_limits,
            "no_progress_categories": no_progress_categories,
            "no_progress_category_options": no_progress_category_options,
            "auto_notes_enabled": get_auto_notes_enabled(db),
            "auto_notes_excluded_categories": auto_notes_excluded,
            "auto_notes_category_options": auto_notes_category_options,
            "auto_notes_last_run_at": datetime.fromisoformat(last_run_at) if last_run_at else None,
            "auto_notes_last_run_summary": get_setting(db, AUTO_NOTES_LAST_RUN_SUMMARY_KEY, ""),
            "sponsor_segment_categories": get_sponsor_segment_categories(db),
            "sponsor_skip_enabled": get_sponsor_skip_enabled(db),
            "sponsor_segment_category_options": [
                {"value": value, "label": SPONSOR_SEGMENT_CATEGORY_LABELS[value]}
                for value in SPONSOR_SEGMENT_CATEGORY_CHOICES
            ],
            "video_library_asset_options": [
                {"kind": "audio", "text": "Audio"},
                {"kind": "video", "text": "Vidéo"},
                {"kind": "shorts", "text": "Shorts"},
                {"kind": "metadata", "text": "Métadonnées"},
                {"kind": "transcript", "text": "Transcript"},
                {"kind": "imported", "text": "Import manuel"},
            ],
        },
    )


@router.post("/settings")
def settings_form(
    media_root: str = Form(...),
    quota_gb: float = Form(...),
    video_category_labels: str = Form(""),
    db: Session = Depends(get_db),
    video_category_styles: str = Form(""),
    video_library_views: str = Form(""),
    no_progress_categories: list[str] = Form(default=[]),
    screen_time_video_today: int = Form(120),
    screen_time_short_today: int = Form(30),
    screen_time_podcast_today: int = Form(120),
    screen_time_music_today: int = Form(180),
    sponsor_segment_categories: list[str] = Form(default=[]),
    sponsor_skip_enabled: str = Form(default=""),
    auto_notes_enabled: str = Form(default=""),
    auto_notes_excluded_categories: list[str] = Form(default=[]),
):
    styles_value = form_text_value(video_category_styles)
    if styles_value:
        label_styles = parse_video_category_label_styles(styles_value)
    else:
        labels = parse_video_category_labels(form_text_value(video_category_labels))
        label_styles = parse_video_category_label_styles(
            serialize_video_category_labels(labels or DEFAULT_VIDEO_CATEGORY_LABELS)
        )
    save_settings(
        db,
        media_root=media_root,
        global_quota_bytes=int(quota_gb * 1024 * 1024 * 1024),
        category_label_styles=label_styles,
        library_views=parse_video_library_views(form_text_value(video_library_views)),
        no_progress_category_labels=form_list_values(no_progress_categories),
        # Unchecked checkbox: the browser sends nothing, so an empty value means "off".
        auto_notes_enabled=bool(form_text_value(auto_notes_enabled)),
        auto_notes_excluded_category_labels=form_list_values(auto_notes_excluded_categories),
        sponsor_segment_categories=form_list_values(sponsor_segment_categories),
        sponsor_skip_enabled=bool(form_text_value(sponsor_skip_enabled)),
        screen_time_today_minutes={
            "video": screen_time_video_today,
            "short": screen_time_short_today,
            "podcast": screen_time_podcast_today,
            "music": screen_time_music_today,
        },
    )
    return redirect("/settings")


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request, db: Session = Depends(get_db), status: str = "all", q: str = "", page: int = 1
):
    status = normalize_log_filter(status)
    query = q.strip()

    # Filter counts and the 24 h summary ignore `q`: they describe the whole table.
    totals = dict(
        db.execute(select(DownloadJob.status, func.count()).group_by(DownloadJob.status)).all()
    )
    since = datetime.now(UTC) - timedelta(hours=24)
    recent = dict(
        db.execute(
            select(DownloadJob.status, func.count())
            .where(DownloadJob.created_at >= since)
            .group_by(DownloadJob.status)
        ).all()
    )

    def count(counts: dict[str, int], statuses: frozenset[str] | None) -> int:
        return (
            sum(counts.values())
            if statuses is None
            else sum(counts.get(name, 0) for name in statuses)
        )

    filters = [
        {"key": key, "label": label, "count": count(totals, statuses), "active": key == status}
        for key, (label, statuses) in LOG_FILTERS.items()
    ]

    # Search spans the message, the video title and the channel name (outer joins: system jobs have neither).
    statement = (
        select(DownloadJob)
        .outerjoin(DownloadJob.channel)
        .outerjoin(DownloadJob.video)
        .options(contains_eager(DownloadJob.channel), contains_eager(DownloadJob.video))
    )
    statuses = LOG_FILTERS[status][1]
    if statuses is not None:
        statement = statement.where(DownloadJob.status.in_(statuses))
    if query:
        pattern = _like_pattern(query)
        statement = statement.where(
            or_(
                DownloadJob.message.ilike(pattern, escape="\\"),
                Video.title.ilike(pattern, escape="\\"),
                Channel.name.ilike(pattern, escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    total_pages = max(1, -(-total // LOG_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    jobs = list(
        db.scalars(
            statement.order_by(desc(DownloadJob.created_at), desc(DownloadJob.id))
            .limit(LOG_PAGE_SIZE)
            .offset((page - 1) * LOG_PAGE_SIZE)
        ).unique()
    )
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            # UTC like the stored created_at values the jobs are grouped by; the local date would
            # mislabel jobs when the server's timezone is behind UTC.
            "days": log_days(jobs, datetime.now(UTC).date()),
            "filters": filters,
            "selected_filter": status,
            "search_query": query,
            "total_jobs": total,
            "errors_24h": count(recent, LOG_FILTERS["errors"][1]),
            "warnings_24h": count(recent, LOG_FILTERS["warnings"][1]),
            "running_jobs": count(totals, LOG_FILTERS["running"][1]),
            "page": page,
            "total_pages": total_pages,
            "page_href": page_href_builder(request),
        },
    )
