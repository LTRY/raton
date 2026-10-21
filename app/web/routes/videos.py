from urllib.parse import urlencode

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
from app.models.video import Video
from app.services.common.categories import parse_video_category_labels
from app.services.common.job_log import log_job
from app.services.common.ratings import InvalidRatingError, check_rating, set_rating
from app.services.common.settings import (
    get_no_progress_category_labels,
    get_video_category_label_styles,
)
from app.services.ingest.channel_exploration import (
    CHANNEL_IMPORT_PROGRESS_LIMIT,
)
from app.services.ingest.identity import ensure_video_channel
from app.services.ingest.local_upload import LocalUploadError, import_local_media
from app.services.ingest.metadata_import import import_video_metadata
from app.services.jobs.download_requests import (
    InvalidMediaFormatError,
    ManualDownloadRefusedError,
    NotAYouTubeLinkError,
    import_shared_video,
    queue_manual_download,
    queue_media_download,
)
from app.services.jobs.downloads import (
    CHANNEL_VIDEO_PAGE_SIZE,
    run_manual_download_job,
    run_media_download_job,
)
from app.services.videos.detail_view import VideoNotFoundError, open_video_detail
from app.services.videos.editing import (
    set_video_categories,
    set_video_comment,
)
from app.services.videos.library_view import (
    downloaded_video_card,
    library_cards,
    library_channels,
    library_listing,
    library_saved_views,
)
from app.services.youtube.sponsor_segments import (
    SponsorSegmentsFetchError,
    refresh_sponsor_segments,
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
        rows = refresh_sponsor_segments(db, video)
    except SponsorSegmentsFetchError as exc:
        message = str(exc)
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
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    media_type: list[str] = Form(...),
    download_transcript: bool = Form(False),
    video_quality: str = Form("1080"),
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/videos/import", alias="next"),
    db: Session = Depends(get_db),
):
    """The no-JS fallback of the import form, which app.js sends to POST /api/videos/import."""
    target = internal_return_path(return_to, "/videos/import")
    categories = [
        *form_list_values(preset_categories),
        *parse_video_category_labels(form_text_value(custom_categories)),
    ]
    try:
        job, download = queue_manual_download(
            db,
            url,
            media_type,
            download_transcript,
            form_text_value(video_quality) or "1080",
            categories,
        )
    except ManualDownloadRefusedError as exc:
        return redirect(append_query(target, {"level": "error", "message": str(exc)}))
    background_tasks.add_task(run_manual_download_job, job.id, *download.run_args())
    return redirect(append_query(target, {"message": "Téléchargement lancé en arrière-plan."}))


@router.post("/videos/upload")
def upload_local_media(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """The no-JS fallback of the drop zone, which app.js sends to POST /api/videos/upload."""
    try:
        video, created = import_local_media(db, file.filename or "", file.file)
    except LocalUploadError as exc:
        return redirect(append_query("/videos/import", {"level": "error", "message": str(exc)}))
    message = "Fichier importé." if created else "Ce fichier est déjà dans la bibliothèque."
    return redirect(append_query(f"/videos/{video.id}", {"message": message}))


@router.post("/videos/share-import")
def share_import_video(request: Request, url: str = Form(...), db: Session = Depends(get_db)):
    """Entry point of the iOS Shortcut living in the share sheet (its URL is set on the phone, so
    it stays out of /api): waits for the import so the Shortcut can open the new fiche. Always
    answers JSON. Sync on purpose: runs in FastAPI's thread pool."""
    try:
        job = import_shared_video(db, url)
    except NotAYouTubeLinkError as exc:
        return JSONResponse({"status": "failed", "message": str(exc)}, status_code=400)
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


@router.post("/videos/{video_id}/media/{media_type}/download")
def download_video_media_form(
    background_tasks: BackgroundTasks,
    video_id: int,
    media_type: str,
    video_quality: str = Form("1080"),
    return_to: str = Form("", alias="next"),
    db: Session = Depends(get_db),
):
    """The no-JS fallback of a short tile's download, which app.js sends to /api."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    target = internal_return_path(return_to, "") if isinstance(return_to, str) else ""
    video_quality = form_text_value(video_quality) or "1080"
    try:
        job = queue_media_download(db, video, media_type, video_quality)
    except InvalidMediaFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_media_download_job, job.id, video.url, media_type, video_quality)
    return redirect(
        append_query(
            target or f"/videos/{video_id}", {"message": "Téléchargement lancé en arrière-plan."}
        )
    )


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


@router.post("/videos/{video_id}/rating")
def rate_video_form(
    video_id: int,
    rating: int = Form(...),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
):
    """The no-JS fallback of the stars, which app.js saves with PUT /api/.../rating."""
    video = db.get(Video, video_id)
    try:
        check_rating(rating)
        if video:
            set_rating(db, video, rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return redirect(internal_return_path(return_to))
