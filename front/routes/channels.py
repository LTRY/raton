from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from front.api import Api, ApiError, get_api
from front.formatting import category_style_map
from front.forms import bell_section, bell_section_label, labels_text, submitted_categories
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

router = APIRouter()

ADDED_CHANNEL_PARAM = "added_channel_id"
YOUTUBE_SEARCH_PARAM = "youtube_q"
YOUTUBE_SEARCH_CATEGORIES_PARAM = "youtube_categories"
# One-shot parameters: kept out of the page's links and `next` so that coming
# back from another action neither replays the toast nor re-runs the search.
ONE_SHOT_PARAMS = (ADDED_CHANNEL_PARAM, YOUTUBE_SEARCH_PARAM, YOUTUBE_SEARCH_CATEGORIES_PARAM)


def youtube_channel_search(request: Request, api: Api) -> dict | None:
    """Candidates for the name typed in the add form, flagged when already in the library."""
    query = request.query_params.get(YOUTUBE_SEARCH_PARAM, "").strip()
    if not query:
        return None
    search = {
        "query": query,
        "categories": request.query_params.get(YOUTUBE_SEARCH_CATEGORIES_PARAM, ""),
        "results": [],
        "error": None,
    }
    try:
        search["results"] = record(api.get("/youtube/channels", q=query))
    except ApiError as exc:
        search["error"] = exc.detail
    return search


def rated_filter(request: Request) -> bool:
    """The Notées switch: on by default; `favorite` is its old name in bookmarked links."""
    for name in ("rated", "favorite"):
        values = request.query_params.getlist(name)
        if values:
            return values[-1].lower() == "true"
    return True


def channels_context(request: Request, page: int, api: Api) -> dict:
    rated = rated_filter(request)
    listed = record(
        api.get(
            "/channels",
            sort=request.query_params.get("sort"),
            rated="true" if rated else "false",
            q=request.query_params.get("q"),
            page=max(page, 1),
        )
    )
    styles = record(api.get("/categories"))
    added_channel_id = request.query_params.get(ADDED_CHANNEL_PARAM, "")
    added_channel = None
    if added_channel_id.isdecimal():
        try:
            added_channel = record(api.get(f"/channels/{added_channel_id}"))
        except ApiError:
            added_channel = None
    return {
        "added_channel": added_channel,
        "channel_entries": [{"channel": item, **vars(item)} for item in listed.items],
        "channel_count": listed.channel_count,
        "rated_filter": rated,
        "search_query": " ".join((request.query_params.get("q") or "").split()),
        "selected_sort": listed.sort,
        "current_channels_path": current_request_path(request, exclude=ONE_SHOT_PARAMS),
        "category_filter_options": styles,
        "category_option_labels": [style.label for style in styles],
        "category_style_map": category_style_map(styles),
        "page": listed.page,
        "total_pages": listed.total_pages,
        "page_href": page_href_builder(request, exclude=ONE_SHOT_PARAMS),
        **message_context(request),
        "csv_preview": None,
        "youtube_search": youtube_channel_search(request, api),
    }


@router.get("/channels", response_class=HTMLResponse)
def channels_page(request: Request, page: int = 1, api: Api = Depends(get_api)):
    return templates.TemplateResponse(
        request, "channels.html", channels_context(request, page, api)
    )


@router.post("/channels/import-csv", response_class=HTMLResponse)
def import_channels_csv_preview(
    request: Request, csv_file: UploadFile = File(...), api: Api = Depends(get_api)
):
    """The preview of a subscriptions CSV, on the channels page; nothing is added yet."""
    try:
        preview = record(
            api.post(
                "/channels/import-csv",
                files={"file": (csv_file.filename or "abonnements.csv", csv_file.file.read())},
            )
        )
    except ApiError as exc:
        return redirect(append_query("/channels", {"level": "error", "message": exc.detail}))
    context = channels_context(request, 1, api)
    context["csv_preview"] = preview
    return templates.TemplateResponse(request, "channels.html", context)


@router.post("/channels/import-csv/confirm")
def import_channels_csv_confirm(
    import_rows: list[str] = Form(default=[]), api: Api = Depends(get_api)
):
    added = api.post("/channels/import-csv/confirm", {"tokens": import_rows})["added"]
    if added == 0:
        return redirect(
            append_query(
                "/channels", {"level": "error", "message": "Aucune nouvelle chaîne à ajouter."}
            )
        )
    plural = "s" if added != 1 else ""
    return redirect(
        append_query(
            "/channels", {"sort": "added", "message": f"{added} chaîne{plural} ajoutée{plural}."}
        )
    )


@router.post("/channels")
def add_channel(
    url: str = Form(...),
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    api: Api = Depends(get_api),
):
    categories = submitted_categories(preset_categories, custom_categories)
    try:
        channel = api.post("/channels", {"url": url, "categories": categories})
    except ApiError as exc:
        if exc.status == 422:
            # A name, not a URL or @handle: it can match several channels, so show the
            # candidates instead of guessing.
            return redirect(
                append_query(
                    "/channels",
                    {
                        YOUTUBE_SEARCH_PARAM: url.strip(),
                        YOUTUBE_SEARCH_CATEGORIES_PARAM: labels_text(categories),
                    },
                )
            )
        if exc.status == 409:
            return redirect(append_query("/channels", {"level": "error", "message": exc.detail}))
        raise
    return redirect(
        append_query("/channels", {"sort": "added", ADDED_CHANNEL_PARAM: str(channel["id"])})
    )


@router.post("/channels/{channel_id}/rating")
def rate_channel_form(
    channel_id: int,
    rating: int = Form(...),
    return_to: str = Form("/channels", alias="next"),
    api: Api = Depends(get_api),
):
    """The no-JS fallback of the stars, which app.js saves with PUT /api/.../rating."""
    try:
        api.put(f"/channels/{channel_id}/rating", {"rating": rating})
    except ApiError as exc:
        if exc.status != 404:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return redirect(internal_return_path(return_to))


@router.post("/channels/{channel_id}/categories")
def update_channel_categories_form(
    channel_id: int,
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/channels", alias="next"),
    api: Api = Depends(get_api),
):
    categories = submitted_categories(preset_categories, custom_categories)
    api.put(f"/channels/{channel_id}/categories", {"categories": categories})
    return redirect(internal_return_path(return_to, "/channels"))


@router.post("/channels/{channel_id}/auto-metadata")
def toggle_channel_auto_metadata_form(
    channel_id: int,
    return_to: str = Form("/channels", alias="next"),
    section: str = Form("videos"),
    api: Api = Depends(get_api),
):
    """Toggles one cloche; turning it on syncs the existing catalogue (not as Nouveautés)."""
    channel = api.get(f"/channels/{channel_id}")
    section = bell_section(section)
    field = "auto_shorts_enabled" if section == "shorts" else "auto_metadata_enabled"
    enabled = not channel[field]
    api.put(f"/channels/{channel_id}/bells/{section}", {"enabled": enabled})
    target = internal_return_path(return_to, "/channels")
    label = bell_section_label(section)
    if not enabled:
        message = f"Suivi quotidien des {label} désactivé pour {channel['name']}."
    else:
        message = (
            f"Suivi quotidien des {label} activé pour {channel['name']}. "
            "Synchronisation du catalogue existant lancée."
        )
    return redirect(append_query(target, {"message": message}))


@router.post("/channels/{channel_id}/import-metadata")
def import_channel_metadata_form(
    channel_id: int,
    page: int = Form(1),
    section: str = Form("videos"),
    return_to: str = Form("/videos", alias="next"),
    api: Api = Depends(get_api),
):
    """The no-JS fallback of a channel's exploration, which app.js sends to /api."""
    target = internal_return_path(return_to)
    try:
        api.post(
            f"/channels/{channel_id}/import-metadata",
            {"page": max(page, 1), "section": bell_section(section)},
        )
    except ApiError as exc:
        if exc.status != 404:
            raise
        return redirect(append_query(target, {"level": "error", "message": "Chaîne introuvable."}))
    return redirect(
        append_query(target, {"message": "Import des métadonnées lancé en arrière-plan."})
    )


@router.post("/channels/{channel_id}/refresh-profile")
def refresh_channel_profile_form(
    channel_id: int, return_to: str = Form("/channels", alias="next"), api: Api = Depends(get_api)
):
    started = api.post(f"/channels/{channel_id}/refresh-profile")
    return redirect(
        append_query(internal_return_path(return_to, "/channels"), {"message": started["message"]})
    )


@router.post("/channels/{channel_id}/delete")
def delete_channel_form(
    channel_id: int, return_to: str = Form("/channels", alias="next"), api: Api = Depends(get_api)
):
    try:
        api.delete(f"/channels/{channel_id}")
    except ApiError as exc:
        if exc.status != 404:
            raise
    return redirect(internal_return_path(return_to))
