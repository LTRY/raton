import json
from urllib.parse import urlencode, urlparse

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import and_, case, desc, func, or_, select, true
from sqlalchemy.orm import Session, selectinload

from app.core.config import local_media_path
from app.db.session import get_db
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.playlist import Playlist
from app.models.video import Video
from app.models.video_sponsor_segment import VideoSponsorSegment
from app.services.background_jobs import (
    CHANNEL_VIDEO_PAGE_SIZE,
    _video_analysis_has_image,
    run_manual_download_job,
    run_transcript_retry_job,
)
from app.services.channels.identity import ensure_video_channel
from app.services.channels.media_import import import_video_metadata
from app.services.job_log import log_job, record_playback_activity
from app.services.media.local_upload import LocalUploadError, import_local_media
from app.services.media.media_storage import mark_watched_if_complete
from app.services.search import video_search_rank
from app.services.settings import (
    SPONSOR_SEGMENT_CATEGORY_LABELS,
    add_video_category_labels,
    get_llm_provider_display_label,
    get_llm_provider_name,
    get_no_progress_category_labels,
    get_sponsor_segment_categories,
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
    get_video_library_views,
)
from app.services.youtube.sponsor_segments import (
    normalize_skip_segments,
    replace_video_sponsor_segments,
)
from app.services.youtube.sponsorblock import fetch_sponsorblock_segments
from app.web.formatting import estimate_channel_periodicity, format_duration, format_views
from app.web.playback import latest_playback_positions, playback_activity_view
from app.web.routes.transcript import transcript_context, video_analysis_payload
from app.web.shared import (
    LIBRARY_PAGE_SIZE,
    append_query,
    category_style_map,
    current_request_path,
    form_list_values,
    form_text_value,
    internal_return_path,
    page_href_builder,
    paginate,
    parse_category_labels,
    redirect,
    serialized_category_labels,
    templates,
    video_metadata,
    wants_json,
)
from app.web.video_library import (
    VIDEO_ASSET_FILTER_OPTIONS,
    VIDEO_LIST_STATES,
    default_channel_section,
    downloaded_video_card,
    normalized_channel_id,
    normalized_search_query,
    selected_channel_section,
    selected_video_asset_filters,
    selected_video_category_filters,
    selected_video_excluded_asset_filters,
    selected_video_excluded_category_filters,
    selected_video_filter_mode,
    selected_video_sort,
    shorts_feature_flags,
    video_active_filter_pills,
    video_asset_kind_condition,
    video_filters_clear_href,
    video_filters_condition,
    video_library_view_is_active,
    video_library_view_path,
    video_section_condition,
)

router = APIRouter()

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def normalize_download_media_types(media_type: str | list[str]) -> list[str]:
    media_types = [media_type] if isinstance(media_type, str) else list(media_type)
    normalized = []
    for item in media_types:
        if item not in {"video", "audio", "metadata"}:
            raise ValueError("Le format doit être vidéo, audio ou métadonnées.")
        if item not in normalized:
            normalized.append(item)
    if not normalized:
        raise ValueError("Sélectionne au moins un format.")
    if any(item in normalized for item in ("video", "audio")) and "metadata" not in normalized:
        normalized.append("metadata")
    return normalized


def normalize_subtitle_language(value: str) -> str | None:
    """Empty means "no language imposed": the original track is chosen by `choose_subtitle_track`."""
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not all(char.isalnum() or char in "-_" for char in normalized):
        raise ValueError("Langue de sous-titres invalide.")
    return normalized


def normalize_subtitle_source(value: str) -> str:
    if value not in {"auto", "manual", "both", "none"}:
        raise ValueError("Source de sous-titres invalide.")
    return value


def normalize_video_quality(value: str) -> str:
    if value not in {"360", "480", "720", "1080", "1440", "2160", "best"}:
        raise ValueError("Qualité vidéo invalide.")
    return value


@router.get("/videos", response_class=HTMLResponse)
def videos_page(
    request: Request,
    channel_id: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    page = max(page, 1)
    selected_channel_id = normalized_channel_id(channel_id)
    selected_channel = db.get(Channel, selected_channel_id) if selected_channel_id else None
    current_channel_section = selected_channel_section(
        request, selected_channel_id, default_channel_section(selected_channel)
    )
    selected_sort = selected_video_sort(request, selected_channel_id)
    if selected_sort == "published":
        order_by = (desc(Video.published_at), desc(Video.downloaded_at), desc(Video.id))
    elif selected_sort == "rated":
        order_by = (
            desc(Video.rating),
            desc(Video.published_at),
            desc(Video.downloaded_at),
            desc(Video.id),
        )
    elif selected_sort == "views":
        # Ties keep the "imported" order, as the former in-Python stable sort did.
        order_by = (
            desc(func.coalesce(Video.view_count, 0)),
            desc(Video.downloaded_at),
            desc(Video.created_at),
            desc(Video.id),
        )
    else:
        order_by = (desc(Video.downloaded_at), desc(Video.created_at), desc(Video.id))
    selected_asset_filters = selected_video_asset_filters(request, selected_channel_id)
    selected_category_filters = selected_video_category_filters(request)
    selected_excluded_asset_filters = selected_video_excluded_asset_filters(request)
    selected_excluded_category_filters = selected_video_excluded_category_filters(request)
    selected_rated_only = request.query_params.get("rated") == "1"
    selected_hide_hidden = request.query_params.get("hide_hidden") == "1"
    selected_uncategorized_only = request.query_params.get("uncategorized") == "1"
    selected_asset_filter_mode = selected_video_filter_mode(request, "asset_filter_mode")
    selected_category_filter_mode = selected_video_filter_mode(request, "category_filter_mode")
    search_query = normalized_search_query(request.query_params.get("q"))

    # Everything but the displayed page is computed in SQL: the library holds thousands of videos and
    # this page must not load them all (docs/spec/11-interface-html.md, "Temps de chargement des pages").
    in_channel = Video.channel_id == selected_channel_id if selected_channel_id else true()
    in_section = video_section_condition(current_channel_section) if selected_channel_id else true()
    matches_filters = video_filters_condition(
        selected_asset_filters,
        selected_category_filters,
        selected_excluded_asset_filters,
        selected_excluded_category_filters,
        selected_rated_only,
        selected_asset_filter_mode,
        selected_category_filter_mode,
        selected_hide_hidden,
        selected_uncategorized_only,
    )
    with_channel = Video.channel_id == Channel.id
    listed = (
        select(Video)
        .outerjoin(Channel, with_channel)
        .where(in_channel, in_section, matches_filters)
        .options(selectinload(Video.channel))
        .order_by(*order_by)
    )
    if search_query:
        # Word-based, accent-insensitive ranking is Python-only: rank the SQL-filtered candidates.
        ranked = [(video_search_rank(video, search_query), video) for video in db.scalars(listed)]
        # Stable sort: the selected sort still orders videos inside a relevance tier.
        matching = [
            video
            for rank, video in sorted((r for r in ranked if r[0] is not None), key=lambda r: r[0])
        ]
        filtered_video_count = len(matching)
        videos, page, total_pages = paginate(matching, page)
    else:
        filtered_video_count = db.scalar(
            select(func.count(Video.id))
            .outerjoin(Channel, with_channel)
            .where(in_channel, in_section, matches_filters)
        )
        total_pages = max(1, -(-filtered_video_count // LIBRARY_PAGE_SIZE))
        page = min(page, total_pages)
        videos = list(
            db.scalars(listed.offset((page - 1) * LIBRARY_PAGE_SIZE).limit(LIBRARY_PAGE_SIZE))
        )
    for video in videos:
        ensure_video_channel(db, video)
    video_cards = [downloaded_video_card(video) for video in videos]
    video_ids = [video.id for video in videos]
    latest_playback_by_video_id = {}
    if video_ids:
        playback_jobs = db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == "played", DownloadJob.video_id.in_(video_ids))
            .order_by(desc(DownloadJob.created_at))
        )
        for job in playback_jobs:
            if job.video_id in latest_playback_by_video_id:
                continue
            playback = playback_activity_view(job)
            if playback:
                latest_playback_by_video_id[job.video_id] = playback
    for card in video_cards:
        card["playback"] = latest_playback_by_video_id.get(card["video"].id)

    def count_where(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    is_short = video_section_condition("shorts")
    has_media = or_(video_asset_kind_condition("video"), video_asset_kind_condition("audio"))
    (
        local_video_count,
        downloaded_video_count,
        metadata_video_count,
        downloaded_regular_video_count,
        downloaded_short_count,
    ) = db.execute(
        select(
            count_where(in_section),
            count_where(and_(in_section, has_media)),
            count_where(and_(in_section, video_asset_kind_condition("metadata"))),
            count_where(and_(has_media, ~is_short)),
            count_where(and_(has_media, is_short)),
        ).where(in_channel)
    ).one()
    next_import_page = (local_video_count // CHANNEL_VIDEO_PAGE_SIZE) + 1
    channel_periodicity = None
    if selected_channel_id:
        published_dates = db.scalars(
            select(Video.published_at).where(
                in_channel, in_section, Video.published_at.is_not(None)
            )
        )
        channel_periodicity = estimate_channel_periodicity(published_dates)
    has_next_page = False
    total_channel_pages = None
    category_label_styles = get_video_category_label_styles(db)
    active_filter_pills = video_active_filter_pills(
        request,
        selected_asset_filters,
        selected_excluded_asset_filters,
        selected_category_filters,
        selected_excluded_category_filters,
        selected_rated_only,
        selected_hide_hidden,
        selected_channel_id,
        selected_uncategorized_only,
    )
    category_filter_count = (
        len(selected_category_filters)
        + len(selected_excluded_category_filters)
        + int(selected_uncategorized_only)
    )
    library_views = [
        {
            **view,
            "href": video_library_view_path(view, request),
            "active": video_library_view_is_active(
                view,
                selected_asset_filters,
                selected_category_filters,
                selected_excluded_asset_filters,
                selected_excluded_category_filters,
                selected_rated_only,
                selected_asset_filter_mode,
                selected_category_filter_mode,
            ),
        }
        for view in get_video_library_views(db)
    ]
    return templates.TemplateResponse(
        request,
        "channel_videos.html" if selected_channel else "videos.html",
        {
            "videos": videos,
            "channels": list(db.scalars(select(Channel).order_by(Channel.name))),
            "selected_channel": selected_channel,
            "selected_channel_id": selected_channel_id,
            "selected_channel_section": current_channel_section,
            "asset_filter_options": VIDEO_ASSET_FILTER_OPTIONS,
            "selected_asset_filters": selected_asset_filters,
            "category_filter_options": category_label_styles,
            "category_style_map": category_style_map(category_label_styles),
            "library_views": library_views,
            "selected_category_filters": selected_category_filters,
            "selected_excluded_asset_filters": selected_excluded_asset_filters,
            "selected_excluded_category_filters": selected_excluded_category_filters,
            "selected_rated_only": selected_rated_only,
            "selected_hide_hidden": selected_hide_hidden,
            "selected_uncategorized_only": selected_uncategorized_only,
            "selected_asset_filter_mode": selected_asset_filter_mode,
            "selected_category_filter_mode": selected_category_filter_mode,
            "selected_sort": selected_sort,
            "search_query": search_query,
            "active_filter_pills": active_filter_pills,
            "category_filter_count": category_filter_count,
            "filters_clear_href": video_filters_clear_href(request),
            "current_videos_path": current_request_path(request),
            "channel_page": page,
            "channel_page_size": CHANNEL_VIDEO_PAGE_SIZE,
            "page": page,
            "total_pages": total_pages,
            "page_href": page_href_builder(request),
            "filtered_video_count": filtered_video_count,
            "local_video_count": local_video_count,
            "downloaded_video_count": downloaded_video_count,
            "downloaded_regular_video_count": downloaded_regular_video_count,
            "downloaded_short_count": downloaded_short_count,
            "metadata_video_count": metadata_video_count,
            "next_import_page": next_import_page,
            "channel_periodicity": channel_periodicity,
            "total_channel_pages": total_channel_pages,
            "has_next_channel_page": has_next_page,
            "video_cards": video_cards,
            "shorts_feature_flags": shorts_feature_flags(video_cards),
            "no_progress_categories": get_no_progress_category_labels(db),
            "channel_entries_error": None,
            "message": request.query_params.get("message"),
            "message_level": request.query_params.get("level", "success"),
        },
    )


@router.post("/videos/{video_id}/categories")
def update_video_categories_form(
    request: Request,
    video_id: int,
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    submitted_categories = [
        *form_list_values(preset_categories),
        *parse_category_labels(form_text_value(custom_categories)),
    ]
    video.category_labels = serialized_category_labels(submitted_categories)
    add_video_category_labels(db, submitted_categories)
    db.commit()
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse({"status": "ok", "categories": submitted_categories})
    return redirect(internal_return_path(return_to, f"/videos/{video_id}"))


@router.post("/videos/{video_id}/comment")
def update_video_comment_form(
    video_id: int,
    comment: str = Form(""),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    comment_text = form_text_value(comment).strip()
    video.comment = comment_text or None
    db.commit()
    return redirect(internal_return_path(return_to, f"/videos/{video_id}"))


_TITLE_STATUS_SUFFIXES = (" ✨", " ✏️")


@router.post("/videos/{video_id}/apply-title")
def apply_video_title_form(
    video_id: int,
    title_choice: str = Form(""),
    title_custom: str = Form(""),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    analysis = json.loads(video.ai_analysis_json) if video.ai_analysis_json else {}
    suggested_titles = analysis.get("suggested_titles") or []

    choice = form_text_value(title_choice).strip()
    chosen_title = ""
    is_ai_choice = False
    if choice in {"1", "2", "3"}:
        index = int(choice) - 1
        if index < len(suggested_titles):
            chosen_title = suggested_titles[index].strip()
            is_ai_choice = True
    if not chosen_title:
        chosen_title = form_text_value(title_custom).strip()
        is_ai_choice = False

    if not chosen_title:
        query = urlencode({"level": "error", "message": "Le titre ne peut pas être vide."})
        return redirect(f"/videos/{video_id}?{query}#transcript-analysis")

    for suffix in _TITLE_STATUS_SUFFIXES:
        if chosen_title.endswith(suffix):
            chosen_title = chosen_title[: -len(suffix)]
            break
    chosen_title = f"{chosen_title} {'✨' if is_ai_choice else '✏️'}"

    video.title = chosen_title
    db.commit()
    return redirect(internal_return_path(return_to, f"/videos/{video_id}"))


@router.post("/videos/{video_id}/sponsors/fetch")
def fetch_video_sponsorblock_segments(
    request: Request, video_id: int, db: Session = Depends(get_db)
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    is_fetch = request.headers.get("x-requested-with") == "fetch"
    try:
        categories = get_sponsor_segment_categories(db)
        segments = fetch_sponsorblock_segments(video.yt_video_id, categories)
        rows = replace_video_sponsor_segments(db, video.id, "sponsorblock", segments)
    except Exception as exc:
        db.rollback()
        message = f"Recherche SponsorBlock impossible : {exc}"
        if is_fetch:
            return JSONResponse({"status": "failed", "message": message}, status_code=400)
        query = urlencode({"level": "error", "message": message})
        return redirect(f"/videos/{video_id}?{query}#segments-sponsors")
    count = len(rows)
    message = (
        f"{count} segment{'s' if count != 1 else ''} trouvé{'s' if count != 1 else ''}."
        if count
        else "Aucun segment SponsorBlock trouvé."
    )
    if is_fetch:
        return JSONResponse({"status": "ok", "message": message})
    query = urlencode({"message": message})
    return redirect(f"/videos/{video_id}?{query}#segments-sponsors")


def _back_label(back_path: str) -> str:
    if back_path.startswith("/playlists/"):
        return "Retour à la playlist"
    if "channel_id=" in back_path:
        return "Retour à la chaîne"
    return "Retour à la bibliothèque"


# Declared before `/videos/{video_id}`, which would otherwise capture "import" and answer 422.
@router.post("/jobs/{job_id}/cancel")
def cancel_channel_import_job(job_id: int, db: Session = Depends(get_db)):
    """Stop a channel exploration: the running import notices it before its next video."""
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if job.channel_id is not None and job.video_id is None and job.status in {"queued", "running"}:
        job.status = "cancelled"
        job.message = "Exploration arrêtée."
        db.commit()
    return {
        "id": job.id,
        "status": job.status,
        "done": job.status in {"downloaded", "metadata", "failed", "cancelled"},
    }


@router.get("/videos/cards", response_class=HTMLResponse)
def video_cards_fragment(
    request: Request,
    ids: str = "",
    section: str = "videos",
    db: Session = Depends(get_db),
):
    """The cards of the given videos, for a channel page that receives imports while it is open."""
    wanted = [int(part) for part in ids.split(",") if part.strip().isdigit()][
        :CHANNEL_IMPORT_PROGRESS_LIMIT
    ]
    videos = []
    if wanted:
        by_id = {
            video.id: video
            for video in db.scalars(
                select(Video).where(Video.id.in_(wanted)).options(selectinload(Video.channel))
            )
        }
        videos = [by_id[video_id] for video_id in wanted if video_id in by_id]
    return templates.TemplateResponse(
        request,
        "_video_cards.html",
        {
            "video_cards": [downloaded_video_card(video) for video in videos],
            "shorts_grid": section in {"short", "shorts"},
            "category_style_map": category_style_map(get_video_category_label_styles(db)),
            "no_progress_categories": get_no_progress_category_labels(db),
            "current_videos_path": internal_return_path(
                request.query_params.get("next", "/videos")
            ),
        },
    )


@router.get("/videos/import", response_class=HTMLResponse)
def import_video_page(request: Request, db: Session = Depends(get_db)):
    category_label_styles = get_video_category_label_styles(db)
    return templates.TemplateResponse(
        request,
        "import_video.html",
        {"category_filter_options": category_label_styles},
    )


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail_page(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    if video.is_new:
        video.is_new = False
        db.commit()

    category_label_styles = get_video_category_label_styles(db)
    query_params = request.query_params if "query_string" in request.scope else {}
    back_path = internal_return_path(query_params.get("next", ""), "/videos")
    context = transcript_context(video)
    vtt_content = None
    if video.subtitle_path:
        subtitle_file = local_media_path(video.subtitle_path)
        if subtitle_file.is_file():
            vtt_content = subtitle_file.read_text(encoding="utf-8", errors="replace")
    raw_metadata = video_metadata(video)
    extended_metadata = {
        "description": raw_metadata.get("description") or None,
        "tags": [tag for tag in (raw_metadata.get("tags") or []) if tag],
        "chapters": [
            {
                "title": chapter["title"],
                "start_label": format_duration(chapter.get("start_time")) or "0:00",
            }
            for chapter in (raw_metadata.get("chapters") or [])
            if isinstance(chapter, dict) and chapter.get("title")
        ],
        "duration": format_duration(raw_metadata.get("duration")),
        "view_count": format_views(raw_metadata.get("view_count")),
        "like_count": format_views(raw_metadata.get("like_count")),
        "comment_count": format_views(raw_metadata.get("comment_count")),
        "uploader": raw_metadata.get("uploader") or raw_metadata.get("channel"),
    }
    extended_metadata["has_content"] = any(
        [
            extended_metadata["description"],
            extended_metadata["tags"],
            extended_metadata["chapters"],
            extended_metadata["view_count"],
            extended_metadata["like_count"],
            extended_metadata["comment_count"],
        ]
    )
    sponsor_categories = get_sponsor_segment_categories(db)
    # `list(...)` est indispensable : le `ScalarResult` de `db.scalars(...)` ne se
    # parcourt qu'une fois, or les lignes servent à la fois à la liste affichée et
    # au payload de saut.
    sponsor_segment_rows = (
        list(
            db.scalars(
                select(VideoSponsorSegment)
                .where(
                    VideoSponsorSegment.video_id == video.id,
                    VideoSponsorSegment.category.in_(sponsor_categories),
                )
                .order_by(VideoSponsorSegment.start_seconds)
            )
        )
        if sponsor_categories
        else []
    )
    sponsor_segments = [
        {
            "category_label": SPONSOR_SEGMENT_CATEGORY_LABELS.get(row.category, row.category),
            "start_seconds": row.start_seconds,
            "start_label": format_duration(row.start_seconds) or "0:00",
            "end_label": format_duration(row.end_seconds) or "0:00",
        }
        for row in sponsor_segment_rows
    ]
    context.update(
        {
            "video": video,
            "category_options": category_label_styles,
            "category_option_labels": [style["label"] for style in category_label_styles],
            "category_style_map": category_style_map(category_label_styles),
            "extended_metadata": extended_metadata,
            "vtt_content": vtt_content,
            "video_analysis": video_analysis_payload(video),
            "can_include_image": _video_analysis_has_image(video, get_llm_provider_name()),
            "sponsor_segments": sponsor_segments,
            "resume_positions": latest_playback_positions(db, video.id),
            "sponsor_skip_payload": {
                "enabled": get_sponsor_skip_enabled(db),
                "segments": normalize_skip_segments(sponsor_segment_rows),
            },
            "back_path": back_path,
            "back_label": _back_label(back_path),
            "video_playlist_links": [
                {"playlist": item.playlist, "item_id": item.id} for item in video.playlist_items
            ],
            "all_playlists": list(db.scalars(select(Playlist).order_by(Playlist.title))),
            "message": query_params.get("message"),
            "message_level": query_params.get("level", "success"),
            "llm_provider_label": get_llm_provider_display_label(),
            "chat_widget_config": {
                "defaultScope": "video",
                "llmProviderLabel": get_llm_provider_display_label(),
                "scopes": {
                    "video": {
                        "askUrl": f"/videos/{video.id}/transcript/chat",
                        "clearUrl": f"/videos/{video.id}/transcript/chat/clear",
                        "jobUrlTemplate": f"/videos/{video.id}/transcript/jobs/" + "{job_id}",
                        "placeholder": "Discuter du contenu",
                        "messages": context["chat_messages"],
                    },
                },
            },
        }
    )
    return templates.TemplateResponse(
        request,
        "video_detail.html",
        context,
    )


@router.post("/videos/download")
def download_video_form(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    media_type: list[str] = Form(...),
    download_transcript: bool = Form(False),
    subtitle_language: str = Form(""),
    subtitle_source: str = Form("both"),
    video_quality: str = Form("1080"),
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/videos/import", alias="next"),
    db: Session = Depends(get_db),
):
    target = internal_return_path(return_to, "/videos/import")
    try:
        media_types = normalize_download_media_types(media_type)
        subtitle_language = normalize_subtitle_language(
            subtitle_language if isinstance(subtitle_language, str) else ""
        )
        subtitle_source = normalize_subtitle_source(
            subtitle_source if isinstance(subtitle_source, str) else "both"
        )
        video_quality = normalize_video_quality(
            video_quality if isinstance(video_quality, str) else "1080"
        )
        submitted_categories = [
            *form_list_values(preset_categories),
            *parse_category_labels(form_text_value(custom_categories)),
        ]
        category_labels = serialized_category_labels(submitted_categories)
        add_video_category_labels(db, submitted_categories)
        job = log_job(db, "queued", "Téléchargement en file d'attente.")
        task_args = [
            job.id,
            url,
            media_types,
            download_transcript,
            category_labels,
            subtitle_language,
            subtitle_source,
        ]
        if video_quality != "1080":
            task_args.append(video_quality)
        background_tasks.add_task(run_manual_download_job, *task_args)
    except Exception as exc:
        db.rollback()
        log_job(db, "failed", f"Manual download failed: {exc}")
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
        return redirect(append_query(target, {"level": "error", "message": str(exc)}))

    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse(
            {
                "job_id": job.id,
                "status": job.status,
                "message": job.message,
                "status_url": f"/videos/download-jobs/{job.id}",
                "return_to": target,
            }
        )
    return redirect(append_query(target, {"message": "Téléchargement lancé en arrière-plan."}))


@router.post("/videos/upload")
def upload_local_media(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import a video or audio file dropped on the import page. Sync on purpose: the file is copied
    in FastAPI's thread pool, and the answer carries the new video's page."""
    try:
        video, created = import_local_media(db, file.filename or "", file.file)
    except LocalUploadError as exc:
        if wants_json(request):
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
        return redirect(append_query("/videos/import", {"level": "error", "message": str(exc)}))
    message = "Fichier importé." if created else "Ce fichier est déjà dans la bibliothèque."
    target = f"/videos/{video.id}"
    if wants_json(request):
        return JSONResponse(
            {"status": "ok", "message": message, "video_id": video.id, "return_to": target}
        )
    return redirect(append_query(target, {"message": message}))


@router.post("/videos/share-import")
def share_import_video(
    request: Request,
    url: str = Form(...),
    db: Session = Depends(get_db),
):
    """Entry point of the iOS Shortcut living in the share sheet: same import as the form's default
    (metadata + transcript, no media file), but it waits for the import so the Shortcut can open the new
    video's page. Always answers JSON, never redirects. Sync on purpose: runs in FastAPI's thread pool."""
    url = url.strip()
    if urlparse(url).hostname not in YOUTUBE_HOSTS:
        return JSONResponse(
            {"status": "failed", "message": "Ce n'est pas un lien YouTube."}, status_code=400
        )
    job = log_job(db, "queued", "Import depuis le partage iOS en file d'attente.")
    run_manual_download_job(job.id, url, ["metadata"], True)
    db.refresh(job)
    if job.status != "downloaded" or job.video_id is None:
        return JSONResponse(
            {"job_id": job.id, "status": "failed", "message": job.message}, status_code=502
        )
    return JSONResponse(
        {
            "job_id": job.id,
            "status": job.status,
            "message": "Import terminé.",
            "video_id": job.video_id,
            # Absolute, built from the Host the phone used (LAN or WireGuard address).
            "video_url": str(request.base_url) + f"videos/{job.video_id}",
        }
    )


@router.get("/videos/download-jobs/{job_id}")
def download_job_status(job_id: int, db: Session = Depends(get_db)):
    return job_status(job_id, db)


@router.post("/videos/{video_id}/media/{media_type}/download")
def download_video_media_form(
    request: Request,
    background_tasks: BackgroundTasks,
    video_id: int,
    media_type: str,
    video_quality: str = Form("1080"),
    return_to: str = Form("", alias="next"),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    # `next` is optional: without it the JSON reply carries no `return_to` and the client reloads the current page.
    target = internal_return_path(return_to, "") if isinstance(return_to, str) else ""
    if media_type not in {"audio", "video"}:
        raise HTTPException(status_code=400, detail="Le format doit être vidéo ou audio.")
    try:
        video_quality = normalize_video_quality(
            video_quality if isinstance(video_quality, str) else "1080"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = log_job(db, "queued", "Téléchargement en file d'attente.", video_id=video.id)
    background_tasks.add_task(
        run_manual_download_job,
        job.id,
        video.url,
        [media_type, "metadata"],
        False,
        video_quality=video_quality,
    )
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse(
            {
                "job_id": job.id,
                "status": job.status,
                "message": job.message,
                "status_url": f"/videos/download-jobs/{job.id}",
                **({"return_to": target} if target else {}),
            }
        )
    return redirect(
        append_query(
            target or f"/videos/{video_id}", {"message": "Téléchargement lancé en arrière-plan."}
        )
    )


@router.post("/videos/{video_id}/transcript/download")
def retry_video_transcript_form(
    request: Request,
    background_tasks: BackgroundTasks,
    video_id: int,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    job = log_job(db, "queued", "Récupération du transcript en file d'attente.", video_id=video.id)
    background_tasks.add_task(run_transcript_retry_job, job.id, video.id)
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse(
            {
                "job_id": job.id,
                "status": job.status,
                "message": job.message,
                "status_url": f"/videos/download-jobs/{job.id}",
            }
        )
    return redirect(
        append_query(
            f"/videos/{video_id}", {"message": "Récupération du transcript lancée en arrière-plan."}
        )
    )


@router.post("/videos/{video_id}/activity")
def log_video_activity(
    video_id: int,
    media_type: str = Form("video"),
    position_seconds: float = Form(0),
    duration_seconds: float = Form(0),
    watched_seconds: float = Form(0),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    if media_type not in {"video", "audio"}:
        raise HTTPException(status_code=400, detail="Type de média invalide")

    mark_watched_if_complete(video, position_seconds, duration_seconds)
    record_playback_activity(
        db, video, media_type, position_seconds, duration_seconds, watched_seconds
    )
    return {"status": "logged"}


# Statuses of the queue row of a channel import job, the only ones that list the videos it brought in.
CHANNEL_IMPORT_PROGRESS_STATUSES = {"queued", "running", "metadata", "cancelled"}
CHANNEL_IMPORT_PROGRESS_LIMIT = 200


@router.get("/jobs/{job_id}")
def job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    payload = {
        "id": job.id,
        "status": job.status,
        "message": job.message,
        "video_id": job.video_id,
        "done": job.status in {"downloaded", "metadata", "failed", "cancelled"},
    }
    if (
        job.channel_id is not None
        and job.video_id is None
        and job.status in CHANNEL_IMPORT_PROGRESS_STATUSES
    ):
        # The import logs one "metadata" row per video, after the queue row: ids are monotonic, so
        # "newer than the queue row" is enough, with no clock comparison.
        imported = db.execute(
            select(Video.id, Video.title)
            .join(DownloadJob, DownloadJob.video_id == Video.id)
            .where(
                DownloadJob.status == "metadata",
                DownloadJob.channel_id == job.channel_id,
                DownloadJob.id > job.id,
            )
            .order_by(DownloadJob.id)
            .limit(CHANNEL_IMPORT_PROGRESS_LIMIT)
        ).all()
        payload["videos"] = [{"id": video_id, "title": title} for video_id, title in imported]
    return payload


@router.post("/videos/import-metadata")
def import_video_metadata_form(
    url: str = Form(...),
    channel_id: int | None = Form(None),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    page = max(page, 1)
    try:
        video = import_video_metadata(db, url, channel_id)
    except Exception as exc:
        db.rollback()
        log_job(db, "failed", f"Metadata import failed: {exc}", channel_id=channel_id)
        query = urlencode({"level": "error", "message": str(exc)})
        target = f"/videos?channel_id={channel_id}&page={page}" if channel_id else "/videos"
        return redirect(f"{target}&{query}" if "?" in target else f"{target}?{query}")

    query = urlencode({"message": f"Infos importées pour {video.title}."})
    target = f"/videos?channel_id={channel_id}&page={page}" if channel_id else "/videos"
    return redirect(f"{target}&{query}" if "?" in target else f"{target}?{query}")


@router.post("/videos/{video_id}/list-state")
def set_video_list_state(
    video_id: int,
    state: str = Form(...),
    db: Session = Depends(get_db),
):
    if state != "clear" and state not in VIDEO_LIST_STATES:
        raise HTTPException(status_code=400, detail="État de liste inconnu.")
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")
    video.list_state = None if state == "clear" else state
    db.commit()
    return JSONResponse({"state": video.list_state})


@router.post("/videos/{video_id}/rating")
def rate_video_form(
    video_id: int,
    rating: int = Form(...),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
    request: Request = None,
):
    if rating < 0 or rating > 5:
        raise HTTPException(status_code=400, detail="La note doit être comprise entre 0 et 5.")
    video = db.get(Video, video_id)
    if video:
        video.rating = rating
        db.commit()
    if wants_json(request):
        if not video:
            raise HTTPException(status_code=404, detail="Vidéo introuvable.")
        return JSONResponse({"rating": video.rating})
    return redirect(internal_return_path(return_to))
