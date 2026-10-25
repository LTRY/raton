import random
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from front.api import Api, ApiError, get_api
from front.cards import card_views
from front.formatting import category_style_map, format_duration, format_views
from front.forms import form_text_value, submitted_categories
from front.library import (
    VIDEO_ASSET_FILTER_OPTIONS,
    channel_periodicity,
    library_query,
    library_view_links,
    normalized_channel_id,
    shorts_feature_flags,
    video_active_filter_pills,
    video_filters_clear_href,
)
from front.pages import (
    append_query,
    current_request_path,
    internal_return_path,
    message_context,
    page_href_builder,
    redirect,
)
from front.records import record
from front.templating import templates
from front.video_detail import video_detail_context

router = APIRouter()

# Shown under the raccoon when a channel has no card; one is drawn per render.
CHANNEL_EMPTY_MESSAGES = (
    "Chou blanc",
    "Le frigo est vide",
    "J’ai fouillé partout. Rien",
    "Tu as tout vu ! Reviens plus tard",
    "Je monte la garde, mais il ne se passe rien.",
    "Hmm. Suspect, tout ce vide.",
    "Rien ici. Pour l’instant.",
)


def random_channel_empty_message() -> str:
    return random.choice(CHANNEL_EMPTY_MESSAGES)


templates.env.globals["random_channel_empty_message"] = random_channel_empty_message


@router.get("/videos", response_class=HTMLResponse)
def videos_page(
    request: Request, channel_id: str | None = None, page: int = 1, api: Api = Depends(get_api)
):
    """The library, or a channel's page when `channel_id` names one."""
    selected_channel_id = normalized_channel_id(channel_id)
    library = record(api.get("/library", **library_query(request, selected_channel_id, page)))
    filters = library.filters
    styles = record(api.get("/categories"))
    channel = record(api.get(f"/channels/{library.channel.id}")) if library.channel else None
    cards = card_views(library.items)
    return templates.TemplateResponse(
        request,
        "channel_videos.html" if channel else "videos.html",
        {
            "channels": record(api.get("/channels/names")),
            "selected_channel": channel,
            "selected_channel_id": filters.channel_id,
            "selected_channel_section": library.section,
            "asset_filter_options": VIDEO_ASSET_FILTER_OPTIONS,
            "selected_asset_filters": set(filters.assets),
            "category_filter_options": styles,
            "category_style_map": category_style_map(styles),
            "library_views": library_view_links(library.saved_views, request),
            "selected_category_filters": set(filters.categories),
            "selected_excluded_asset_filters": set(filters.excluded_assets),
            "selected_excluded_category_filters": set(filters.excluded_categories),
            "selected_rated_only": filters.rated,
            "selected_hide_hidden": filters.hide_hidden,
            "selected_uncategorized_only": filters.uncategorized,
            "selected_asset_filter_mode": filters.asset_filter_mode,
            "selected_category_filter_mode": filters.category_filter_mode,
            "selected_sort": filters.sort,
            "search_query": filters.q,
            "active_filter_pills": video_active_filter_pills(request, filters),
            "category_filter_count": len(filters.categories)
            + len(filters.excluded_categories)
            + int(filters.uncategorized),
            "filters_clear_href": video_filters_clear_href(request),
            "current_videos_path": current_request_path(request),
            "channel_page": library.page,
            "channel_page_size": library.explore_page_size,
            "page": library.page,
            "total_pages": library.total_pages,
            "page_href": page_href_builder(request),
            "filtered_video_count": library.total,
            **vars(library.counts),
            "next_import_page": library.explore_next_page,
            "channel_periodicity": channel_periodicity(library.publication_interval_days),
            "video_cards": cards,
            "shorts_feature_flags": shorts_feature_flags(cards),
            **message_context(request),
        },
    )


@router.get("/videos/cards", response_class=HTMLResponse)
def video_cards_fragment(
    request: Request, ids: str = "", section: str = "videos", api: Api = Depends(get_api)
):
    """The cards of the given fiches, for a channel page that receives imports while it is open."""
    styles = record(api.get("/categories"))
    return templates.TemplateResponse(
        request,
        "_video_cards.html",
        {
            "video_cards": card_views(record(api.get("/library/cards", ids=ids))),
            "shorts_grid": section in {"short", "shorts"},
            "category_style_map": category_style_map(styles),
            "current_videos_path": internal_return_path(
                request.query_params.get("next", "/videos")
            ),
        },
    )


@router.get("/videos/import")
def import_video_page(request: Request):
    """The import form is the sheet of the round button: forward to a page that shows it open."""
    return redirect(append_query("/videos", {**request.query_params, "import": "video"}))


def youtube_result_view(result: dict) -> dict:
    """A result of the Recherche section with its French duration and view count."""
    views = format_views(result["view_count"])
    return {
        **result,
        "duration": format_duration(result["duration_seconds"]),
        "views": f"{views} vue{'s' if result['view_count'] > 1 else ''}" if views else None,
    }


@router.get("/videos/recherche", response_class=HTMLResponse)
def youtube_search_page(request: Request, q: str = "", api: Api = Depends(get_api)):
    """The Recherche section of the Bibliothèque: a search on YouTube itself, each video
    added to the library as a fiche or linked to the fiche it already has."""
    query = " ".join(q.split())
    results, error = [], None
    if query:
        try:
            results = [
                youtube_result_view(result) for result in api.get("/youtube/videos", q=query)
            ]
        except ApiError as exc:
            error = exc.detail
    return templates.TemplateResponse(
        request,
        "youtube_search.html",
        {
            "search_query": query,
            "results": results,
            "error": error,
            "library_views": library_view_links(record(api.get("/library/views")), request),
            # The toast params are dropped so an addition does not replay the previous toast.
            "return_path": current_request_path(request, exclude=("message", "level")),
            **message_context(request),
        },
    )


@router.get("/import/categories", response_class=HTMLResponse)
def import_categories(request: Request, api: Api = Depends(get_api)):
    """Category chips of the import sheet: a lazy turbo-frame, so no other page pays for the call."""
    return templates.TemplateResponse(
        request,
        "_import_categories.html",
        {"category_filter_options": record(api.get("/categories"))},
    )


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail_page(request: Request, video_id: int, api: Api = Depends(get_api)):
    # Opening the page takes the fiche out of the Nouveautés.
    api.post(f"/videos/{video_id}/open")
    raw = api.get(f"/videos/{video_id}")
    context = video_detail_context(
        record(raw),
        raw,
        record(api.get("/settings")),
        record(api.get("/playlists", sort="title")),
        internal_return_path(request.query_params.get("next", ""), "/videos"),
    )
    return templates.TemplateResponse(
        request, "video_detail.html", {**context, **message_context(request)}
    )


@router.get("/videos/{video_id}/transcript", response_class=HTMLResponse)
def video_transcript_page(request: Request, video_id: int):
    """Old URL of the transcript: the fiche, opened on its transcript tab."""
    target = f"/videos/{video_id}#transcript"
    if request.url.query:
        target = f"/videos/{video_id}?{request.url.query}#transcript"
    return redirect(target)


@router.post("/videos/{video_id}/transcript/generate")
def generate_video_transcript_documents(video_id: int, api: Api = Depends(get_api)):
    """No-JS fallback of `POST /api/videos/{id}/notes/generate`."""
    try:
        api.post(f"/videos/{video_id}/notes/generate")
    except ApiError as exc:
        if exc.status == 404:
            raise
        query = urlencode({"level": "error", "message": exc.detail})
        return redirect(f"/videos/{video_id}?{query}#transcript")
    return redirect(f"/videos/{video_id}?message=Generation+en+cours...#transcript")


@router.post("/videos/{video_id}/rating")
def rate_video_form(
    video_id: int,
    rating: int = Form(...),
    return_to: str = Form("/videos", alias="next"),
    api: Api = Depends(get_api),
):
    """The no-JS fallback of the stars, which app.js saves with PUT /api/.../rating."""
    try:
        api.put(f"/videos/{video_id}/rating", {"rating": rating})
    except ApiError as exc:
        if exc.status != 404:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return redirect(internal_return_path(return_to))


@router.post("/videos/{video_id}/categories")
def update_video_categories_form(
    video_id: int,
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/videos", alias="next"),
    api: Api = Depends(get_api),
):
    api.put(
        f"/videos/{video_id}/categories",
        {"categories": submitted_categories(preset_categories, custom_categories)},
    )
    return redirect(internal_return_path(return_to, f"/videos/{video_id}"))


@router.post("/videos/{video_id}/comment")
def update_video_comment_form(
    video_id: int,
    comment: str = Form(""),
    return_to: str = Form("/videos", alias="next"),
    api: Api = Depends(get_api),
):
    api.put(f"/videos/{video_id}/comment", {"comment": form_text_value(comment)})
    return redirect(internal_return_path(return_to, f"/videos/{video_id}"))


@router.post("/videos/{video_id}/sponsors/fetch")
def fetch_video_sponsorblock_segments(video_id: int, api: Api = Depends(get_api)):
    try:
        count = api.post(f"/videos/{video_id}/sponsor-segments/fetch")["count"]
    except ApiError as exc:
        if exc.status == 404:
            raise
        query = urlencode({"level": "error", "message": exc.detail})
        return redirect(f"/videos/{video_id}?{query}#segments-sponsors")
    message = (
        f"{count} segment{'s' if count != 1 else ''} trouvé{'s' if count != 1 else ''}."
        if count
        else "Aucun segment SponsorBlock trouvé."
    )
    return redirect(f"/videos/{video_id}?{urlencode({'message': message})}#segments-sponsors")


@router.post("/videos/{video_id}/media/{media_type}/delete")
def delete_video_media_form(
    video_id: int,
    media_type: str,
    return_to: str = Form("/videos", alias="next"),
    api: Api = Depends(get_api),
):
    """The no-JS fallback of a format's deletion, which app.js sends to DELETE /api/..."""
    target = internal_return_path(return_to, f"/videos/{video_id}")
    try:
        api.delete(f"/videos/{video_id}/media/{media_type}")
    except ApiError as exc:
        if exc.status == 404:
            raise
        return redirect(append_query(target, {"level": "error", "message": exc.detail}))
    label = "vidéo" if media_type == "video" else "audio"
    return redirect(append_query(target, {"message": f"Fichier {label} supprimé."}))


@router.post("/videos/{video_id}/media/{media_type}/download")
def download_video_media_form(
    video_id: int,
    media_type: str,
    video_quality: str = Form("1080"),
    return_to: str = Form("", alias="next"),
    api: Api = Depends(get_api),
):
    """The no-JS fallback of a short tile's download, which app.js sends to /api."""
    try:
        api.post(
            f"/videos/{video_id}/media/{media_type}/download",
            {"video_quality": form_text_value(video_quality) or "1080"},
        )
    except ApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    target = internal_return_path(return_to, "")
    return redirect(
        append_query(
            target or f"/videos/{video_id}", {"message": "Téléchargement lancé en arrière-plan."}
        )
    )


@router.post("/videos/download")
def download_video_form(
    url: str = Form(...),
    media_type: list[str] = Form(...),
    download_transcript: bool = Form(False),
    video_quality: str = Form("1080"),
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/videos/import", alias="next"),
    api: Api = Depends(get_api),
):
    """The no-JS fallback of the import form, which app.js sends to POST /api/videos/import."""
    target = internal_return_path(return_to, "/videos/import")
    try:
        api.post(
            "/videos/import",
            {
                "url": url,
                "media_types": media_type,
                "download_transcript": download_transcript,
                "video_quality": form_text_value(video_quality) or "1080",
                "categories": submitted_categories(preset_categories, custom_categories),
            },
        )
    except ApiError as exc:
        if exc.status == 422:
            raise
        return redirect(append_query(target, {"level": "error", "message": exc.detail}))
    return redirect(append_query(target, {"message": "Téléchargement lancé en arrière-plan."}))


@router.post("/videos/upload")
def upload_local_media(file: UploadFile = File(...), api: Api = Depends(get_api)):
    """The no-JS fallback of the drop zone, which app.js sends to POST /api/videos/upload."""
    try:
        uploaded = api.post("/videos/upload", files={"file": (file.filename or "", file.file)})
    except ApiError as exc:
        return redirect(append_query("/videos/import", {"level": "error", "message": exc.detail}))
    message = (
        "Fichier importé." if uploaded["created"] else "Ce fichier est déjà dans la bibliothèque."
    )
    return redirect(append_query(f"/videos/{uploaded['video_id']}", {"message": message}))


@router.post("/videos/share-import")
def share_import_video(request: Request, url: str = Form(...), api: Api = Depends(get_api)):
    """Entry point of the iOS Shortcut of the share sheet (its URL is set on the phone, so it
    keeps this path): waits for the import so the Shortcut can open the new fiche. Always
    answers JSON; the Shortcut reads `video_url`."""
    try:
        imported = api.post("/videos/share-import", {"url": url})
    except ApiError as exc:
        if exc.status == 422:
            raise
        return JSONResponse({"status": "failed", "message": exc.detail}, status_code=exc.status)
    return JSONResponse(
        {
            **imported,
            # Absolute, built from the Host the phone used (LAN or WireGuard address).
            "video_url": str(request.base_url) + f"videos/{imported['video_id']}",
        }
    )
