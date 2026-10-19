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
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.common.categories import parse_video_category_labels, serialized_category_labels
from app.services.common.job_log import JOB_DONE_STATUSES, log_job
from app.services.common.ratings import InvalidRatingError, check_rating, set_rating
from app.services.common.settings import (
    add_video_category_labels,
    get_no_progress_category_labels,
    get_video_category_label_styles,
)
from app.services.ingest.channel_exploration import (
    CHANNEL_IMPORT_PROGRESS_LIMIT,
    cancel_channel_exploration,
    channel_exploration_videos,
)
from app.services.ingest.identity import ensure_video_channel
from app.services.ingest.local_upload import LocalUploadError, import_local_media
from app.services.ingest.metadata_import import import_video_metadata
from app.services.jobs.downloads import (
    CHANNEL_VIDEO_PAGE_SIZE,
    run_manual_download_job,
    run_transcript_retry_job,
)
from app.services.videos.detail_view import VideoNotFoundError, open_video_detail
from app.services.videos.download_options import (
    normalize_download_media_types,
    normalize_subtitle_language,
    normalize_subtitle_source,
    normalize_video_quality,
)
from app.services.videos.editing import (
    set_video_categories,
    set_video_comment,
    set_video_list_state,
)
from app.services.videos.library_view import (
    downloaded_video_card,
    library_cards,
    library_channels,
    library_listing,
    library_saved_views,
)
from app.services.videos.playback import (
    record_playback_activity,
)
from app.services.youtube.sponsor_segments import (
    fetch_sponsor_segments,
)
from app.web.formatting import estimate_channel_periodicity
from app.web.shared import (
    append_query,
    category_style_map,
    current_request_path,
    form_list_values,
    form_text_value,
    internal_return_path,
    page_href_builder,
    redirect,
    templates,
    wants_json,
)
from app.web.video_detail import video_detail_context
from app.web.video_library import (
    VIDEO_ASSET_FILTER_OPTIONS,
    library_filters_from_request,
    shorts_feature_flags,
    video_active_filter_pills,
    video_filters_clear_href,
    video_library_view_path,
)

router = APIRouter()

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


@router.get("/videos", response_class=HTMLResponse)
def videos_page(
    request: Request,
    channel_id: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    filters = library_filters_from_request(request, channel_id, page)
    listing = library_listing(db, filters)
    for video in listing.videos:
        ensure_video_channel(db, video)
    video_cards = library_cards(db, listing.videos)
    next_import_page = (listing.section_counts["local_video_count"] // CHANNEL_VIDEO_PAGE_SIZE) + 1
    channel_periodicity = (
        estimate_channel_periodicity(listing.publication_dates)
        if listing.publication_dates is not None
        else None
    )
    category_label_styles = get_video_category_label_styles(db)
    active_filter_pills = video_active_filter_pills(
        request,
        set(filters.assets),
        set(filters.excluded_assets),
        set(filters.categories),
        set(filters.excluded_categories),
        filters.rated_only,
        filters.hide_hidden,
        filters.channel_id,
        filters.uncategorized_only,
    )
    category_filter_count = (
        len(filters.categories) + len(filters.excluded_categories) + int(filters.uncategorized_only)
    )
    library_views = [
        {**view, "href": video_library_view_path(view, request)}
        for view in library_saved_views(db, filters)
    ]
    return templates.TemplateResponse(
        request,
        "channel_videos.html" if listing.channel else "videos.html",
        {
            "videos": listing.videos,
            "channels": library_channels(db),
            "selected_channel": listing.channel,
            "selected_channel_id": filters.channel_id,
            "selected_channel_section": listing.section,
            "asset_filter_options": VIDEO_ASSET_FILTER_OPTIONS,
            "selected_asset_filters": set(filters.assets),
            "category_filter_options": category_label_styles,
            "category_style_map": category_style_map(category_label_styles),
            "library_views": library_views,
            "selected_category_filters": set(filters.categories),
            "selected_excluded_asset_filters": set(filters.excluded_assets),
            "selected_excluded_category_filters": set(filters.excluded_categories),
            "selected_rated_only": filters.rated_only,
            "selected_hide_hidden": filters.hide_hidden,
            "selected_uncategorized_only": filters.uncategorized_only,
            "selected_asset_filter_mode": filters.asset_filter_mode,
            "selected_category_filter_mode": filters.category_filter_mode,
            "selected_sort": filters.sort,
            "search_query": filters.search_query,
            "active_filter_pills": active_filter_pills,
            "category_filter_count": category_filter_count,
            "filters_clear_href": video_filters_clear_href(request),
            "current_videos_path": current_request_path(request),
            "channel_page": listing.page,
            "channel_page_size": CHANNEL_VIDEO_PAGE_SIZE,
            "page": listing.page,
            "total_pages": listing.total_pages,
            "page_href": page_href_builder(request),
            "filtered_video_count": listing.filtered_video_count,
            **listing.section_counts,
            "next_import_page": next_import_page,
            "channel_periodicity": channel_periodicity,
            "total_channel_pages": None,
            "has_next_channel_page": False,
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
        *parse_video_category_labels(form_text_value(custom_categories)),
    ]
    set_video_categories(db, video, submitted_categories)
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

    set_video_comment(db, video, form_text_value(comment))
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
        rows = fetch_sponsor_segments(db, video)
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


# Declared before `/videos/{video_id}`, which would otherwise capture "import" and answer 422.
@router.post("/jobs/{job_id}/cancel")
def cancel_channel_import_job(job_id: int, db: Session = Depends(get_db)):
    """Stop a channel exploration: the running import notices it before its next video."""
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    cancel_channel_exploration(db, job)
    return {"id": job.id, "status": job.status, "done": job.status in JOB_DONE_STATUSES}


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
    try:
        detail = open_video_detail(db, video_id)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    query_params = request.query_params if "query_string" in request.scope else {}
    back_path = internal_return_path(query_params.get("next", ""), "/videos")
    context = video_detail_context(detail, back_path)
    context["message"] = query_params.get("message")
    context["message_level"] = query_params.get("level", "success")
    return templates.TemplateResponse(request, "video_detail.html", context)


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
            *parse_video_category_labels(form_text_value(custom_categories)),
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

    record_playback_activity(
        db, video, media_type, position_seconds, duration_seconds, watched_seconds
    )
    return {"status": "logged"}


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
        "done": job.status in JOB_DONE_STATUSES,
    }
    imported = channel_exploration_videos(db, job)
    if imported is not None:
        payload["videos"] = imported
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
def set_video_list_state_form(
    video_id: int,
    state: str = Form(...),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")
    try:
        set_video_list_state(db, video, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"state": video.list_state})


@router.post("/videos/{video_id}/rating")
def rate_video_form(
    video_id: int,
    rating: int = Form(...),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
    request: Request = None,
):
    video = db.get(Video, video_id)
    try:
        check_rating(rating)
        if video:
            set_rating(db, video, rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if wants_json(request):
        if not video:
            raise HTTPException(status_code=404, detail="Vidéo introuvable.")
        return JSONResponse({"rating": video.rating})
    return redirect(internal_return_path(return_to))
