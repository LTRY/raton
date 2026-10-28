import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from front.api import Api, get_api
from front.cards import screen_time_rings
from front.forms import form_list_values, form_text_value, split_labels
from front.logs import LOG_FILTER_LABELS, log_days, normalize_log_filter
from front.pages import page_href_builder, redirect
from front.records import record
from front.templating import templates

router = APIRouter()

VIDEO_LIBRARY_ASSET_OPTIONS = [
    {"kind": "audio", "text": "Audio"},
    {"kind": "video", "text": "Vidéo"},
    {"kind": "shorts", "text": "Shorts"},
    {"kind": "metadata", "text": "Métadonnées"},
    {"kind": "transcript", "text": "Transcript"},
    {"kind": "imported", "text": "Import manuel"},
]


def with_unknown_labels(styles: list[dict], labels: list[str]) -> list[dict]:
    """The category chips of a setting: the known categories, then its labels no longer in them."""
    known = {style["label"] for style in styles}
    return styles + [{"label": label, "color": None} for label in labels if label not in known]


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, api: Api = Depends(get_api)):
    settings = api.get("/settings")
    counts = api.get("/stats")
    scan = record(api.get("/scan"))
    auto_notes = record(api.get("/auto-notes"))
    styles = settings["video_category_label_styles"]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "channel_count": counts["channels"],
            "rated_channel_count": counts["rated_channels"],
            "video_count": counts["videos"],
            "regular_video_count": counts["regular_videos"],
            "short_count": counts["shorts"],
            "downloaded_media_count": counts["downloaded_media"],
            "transcript_count": counts["transcripts"],
            "used_bytes": counts["used_bytes"],
            "quota_bytes": counts["quota_bytes"],
            "storage_percent": counts["storage_percent"],
            "playback_time_stats": screen_time_rings(record(api.get("/screen-time"))),
            "llm_usage": record(api.get("/llm/usage")),
            "last_auto_scan": {
                "at": scan.last_at,
                "status": scan.last_status,
                "imported": scan.last_imported,
            },
            "scan_running": scan.running,
            "scan_events_last_id": scan.last_event_id,
            "video_category_labels": "\n".join(settings["video_category_labels"]),
            "video_category_labels_list": settings["video_category_labels"],
            "video_category_label_styles": styles,
            "video_library_views": settings["video_library_views"],
            "screen_time_limits": settings["screen_time_limits"],
            "no_progress_categories": settings["no_progress_category_labels"],
            "no_progress_category_options": with_unknown_labels(
                styles, settings["no_progress_category_labels"]
            ),
            "auto_notes_enabled": settings["auto_notes_enabled"],
            "auto_notes_excluded_categories": settings["auto_notes_excluded_category_labels"],
            "auto_notes_category_options": with_unknown_labels(
                styles, settings["auto_notes_excluded_category_labels"]
            ),
            "auto_notes_last_run_at": auto_notes.last_run_at,
            "auto_notes_last_run_summary": auto_notes.last_run_summary,
            "sponsor_segment_categories": settings["sponsor_segment_categories"],
            "sponsor_skip_enabled": settings["sponsor_skip_enabled"],
            "sponsor_segment_category_options": settings["sponsor_segment_category_choices"],
            "video_library_asset_options": VIDEO_LIBRARY_ASSET_OPTIONS,
        },
    )


def json_list(text: str) -> list:
    """A list typed in a settings editor's JSON field; anything else counts as empty, which the
    API replaces with the defaults."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


@router.post("/settings")
def settings_form(
    video_category_labels: str = Form(""),
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
    api: Api = Depends(get_api),
):
    """The no-JS form of /settings: the colour editor writes its JSON in `video_category_styles`;
    without it the plain list of `video_category_labels` is used."""
    update = {
        "video_library_views": json_list(form_text_value(video_library_views)),
        "no_progress_category_labels": form_list_values(no_progress_categories),
        # Unchecked checkbox: the browser sends nothing, so an empty value means "off".
        "auto_notes_enabled": bool(form_text_value(auto_notes_enabled)),
        "auto_notes_excluded_category_labels": form_list_values(auto_notes_excluded_categories),
        "sponsor_segment_categories": form_list_values(sponsor_segment_categories),
        "sponsor_skip_enabled": bool(form_text_value(sponsor_skip_enabled)),
        "screen_time_today_minutes": {
            "video": screen_time_video_today,
            "short": screen_time_short_today,
            "podcast": screen_time_podcast_today,
            "music": screen_time_music_today,
        },
    }
    styles = form_text_value(video_category_styles)
    if styles:
        update["video_category_label_styles"] = json_list(styles)
    else:
        update["video_category_labels"] = split_labels(form_text_value(video_category_labels))
    api.put("/settings", update)
    return redirect("/settings")


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request, status: str = "all", q: str = "", page: int = 1, api: Api = Depends(get_api)
):
    status = normalize_log_filter(status)
    query = q.strip()
    logs = record(api.get("/logs", filter=status, q=query, page=max(page, 1)))
    counts, recent = logs.filter_counts, logs.last_24h_counts
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            # UTC like the stored created_at values the jobs are grouped by; the local date would
            # mislabel jobs when the server's timezone is behind UTC.
            "days": log_days(logs.rows, datetime.now(UTC).date()),
            "filters": [
                {"key": key, "label": label, "count": counts[key], "active": key == status}
                for key, label in LOG_FILTER_LABELS.items()
            ],
            "selected_filter": status,
            "search_query": query,
            "total_jobs": logs.total,
            "errors_24h": recent.errors,
            "warnings_24h": recent.warnings,
            "running_jobs": counts.running,
            "page": logs.page,
            "total_pages": logs.total_pages,
            "page_href": page_href_builder(request),
        },
    )
