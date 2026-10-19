import logging

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
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.session import get_db
from app.models.channel import Channel
from app.services.channels.listing import (
    CHANNEL_SORTS,
    channel_entries,
    channels_by_yt_id,
    video_counts_by_channel,
)
from app.services.channels.manage import (
    ChannelAlreadyInLibraryError,
    bell_section,
    create_channel,
    delete_channel,
    set_channel_categories,
    toggle_channel_bell,
)
from app.services.channels.subscriptions import (
    SubscriptionsCsvError,
    add_subscriptions,
    parse_subscriptions_csv,
    preview_subscriptions,
)
from app.services.common.categories import parse_video_category_labels, serialized_category_labels
from app.services.common.job_log import log_job
from app.services.common.ratings import InvalidRatingError, check_rating, set_rating
from app.services.common.settings import (
    get_video_category_label_styles,
)
from app.services.jobs.background_jobs import (
    run_channel_metadata_import_job,
    run_channel_profile_backfill_job,
    run_channel_profile_refresh_job,
)
from app.services.youtube.channel_info import (
    ChannelNotFoundError,
    is_channel_reference,
    search_channels,
)
from app.web.shared import (
    append_query,
    category_style_map,
    current_request_path,
    form_list_values,
    form_text_value,
    internal_return_path,
    page_href_builder,
    paginate,
    redirect,
    templates,
    wants_json,
)
from app.web.video_library import normalized_search_query

logger = logging.getLogger(__name__)

router = APIRouter()


ADDED_CHANNEL_PARAM = "added_channel_id"
YOUTUBE_SEARCH_PARAM = "youtube_q"
YOUTUBE_SEARCH_CATEGORIES_PARAM = "youtube_categories"
# One-shot parameters: kept out of the page's links and `next` so that coming
# back from another action neither replays the toast nor re-runs the search.
ONE_SHOT_PARAMS = (ADDED_CHANNEL_PARAM, YOUTUBE_SEARCH_PARAM, YOUTUBE_SEARCH_CATEGORIES_PARAM)


def youtube_channel_search(request: Request, db: Session) -> dict | None:
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
        results = search_channels(query)
    except Exception as exc:
        search["error"] = f"Recherche YouTube impossible : {exc}"
        return search
    known = channels_by_yt_id(db, [result["yt_channel_id"] for result in results])
    search["results"] = [
        {**result, "existing": known.get(result["yt_channel_id"])} for result in results
    ]
    return search


def channels_context(request: Request, rated: bool | None, page: int, db: Session) -> dict:
    search_query = normalized_search_query(request.query_params.get("q"))
    selected_sort = request.query_params.get("sort")
    if selected_sort not in CHANNEL_SORTS:
        selected_sort = "activity"
    rated_values = request.query_params.getlist("rated") if "query_string" in request.scope else []
    legacy_favorite_values = (
        request.query_params.getlist("favorite") if "query_string" in request.scope else []
    )
    if rated_values:
        rated_filter = rated_values[-1].lower() == "true"
    elif legacy_favorite_values:
        rated_filter = legacy_favorite_values[-1].lower() == "true"
    elif rated is not None:
        rated_filter = rated
    else:
        rated_filter = True
    all_channel_entries = channel_entries(db, selected_sort, rated_filter, search_query)
    page_entries, page, total_pages = paginate(all_channel_entries, page)
    # Counted for the visible page only: the card shows how many library entries (fiches) the channel has.
    video_counts = video_counts_by_channel(db, [entry["channel"].id for entry in page_entries])
    for entry in page_entries:
        entry["video_count"] = video_counts.get(entry["channel"].id, 0)
    category_label_styles = get_video_category_label_styles(db)
    added_channel_id = request.query_params.get(ADDED_CHANNEL_PARAM, "")
    added_channel = db.get(Channel, int(added_channel_id)) if added_channel_id.isdecimal() else None
    return {
        "added_channel": added_channel,
        "channel_entries": page_entries,
        "channels": [entry["channel"] for entry in page_entries],
        "total_channel_entry_count": len(all_channel_entries),
        "rated_filter": rated_filter,
        "search_query": search_query,
        "selected_sort": selected_sort,
        "current_channels_path": current_request_path(request, exclude=ONE_SHOT_PARAMS),
        "category_filter_options": category_label_styles,
        "category_option_labels": [style["label"] for style in category_label_styles],
        "category_style_map": category_style_map(category_label_styles),
        "page": page,
        "total_pages": total_pages,
        "page_href": page_href_builder(request, exclude=ONE_SHOT_PARAMS),
        "message": request.query_params.get("message"),
        "message_level": request.query_params.get("level", "success"),
        "csv_preview": None,
        "youtube_search": youtube_channel_search(request, db),
    }


@router.get("/channels", response_class=HTMLResponse)
def channels_page(
    request: Request, rated: bool | None = None, page: int = 1, db: Session = Depends(get_db)
):
    context = channels_context(request, rated, page, db)
    return templates.TemplateResponse(request, "channels.html", context)


@router.post("/channels/import-csv", response_class=HTMLResponse)
def import_channels_csv_preview(
    request: Request,
    csv_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        parsed_rows = parse_subscriptions_csv(csv_file.file.read())
    except SubscriptionsCsvError as exc:
        return redirect(append_query("/channels", {"level": "error", "message": str(exc)}))

    preview_rows = preview_subscriptions(db, parsed_rows)
    new_count = sum(1 for row in preview_rows if not row["already_imported"])

    context = channels_context(request, None, 1, db)
    context["csv_preview"] = {
        "rows": preview_rows,
        "new_count": new_count,
        "existing_count": len(preview_rows) - new_count,
    }
    return templates.TemplateResponse(request, "channels.html", context)


@router.post("/channels/import-csv/confirm")
def import_channels_csv_confirm(
    import_rows: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    added = add_subscriptions(db, import_rows)
    if added and background_tasks is not None:
        background_tasks.add_task(run_channel_profile_backfill_job)

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
    db: Session = Depends(get_db),
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    background_tasks: BackgroundTasks = None,
):
    submitted_categories = [
        *form_list_values(preset_categories),
        *parse_video_category_labels(form_text_value(custom_categories)),
    ]
    category_labels = serialized_category_labels(submitted_categories)
    if not is_channel_reference(url):
        # A name can match several channels: show the candidates instead of guessing.
        return redirect(
            append_query(
                "/channels",
                {
                    YOUTUBE_SEARCH_PARAM: url.strip(),
                    YOUTUBE_SEARCH_CATEGORIES_PARAM: category_labels or "",
                },
            )
        )
    try:
        channel = create_channel(db, url, category_labels=submitted_categories)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Chaîne introuvable") from exc
    except ChannelAlreadyInLibraryError as exc:
        return redirect(append_query("/channels", {"level": "error", "message": str(exc)}))
    if background_tasks is not None:
        background_tasks.add_task(run_channel_profile_backfill_job)
    return redirect(
        append_query("/channels", {"sort": "added", ADDED_CHANNEL_PARAM: str(channel.id)})
    )


@router.post("/channels/{channel_id}/rating")
def rate_channel_form(
    channel_id: int,
    rating: int = Form(...),
    return_to: str = Form("/channels", alias="next"),
    db: Session = Depends(get_db),
    request: Request = None,
):
    channel = db.get(Channel, channel_id)
    try:
        check_rating(rating)
        if channel:
            set_rating(db, channel, rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if wants_json(request):
        if not channel:
            raise HTTPException(status_code=404, detail="Chaîne introuvable")
        return JSONResponse({"rating": channel.rating})
    return redirect(internal_return_path(return_to))


@router.post("/channels/{channel_id}/categories")
def update_channel_categories_form(
    channel_id: int,
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    return_to: str = Form("/channels", alias="next"),
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable")

    submitted_categories = [
        *form_list_values(preset_categories),
        *parse_video_category_labels(form_text_value(custom_categories)),
    ]
    set_channel_categories(db, channel, submitted_categories)
    return redirect(internal_return_path(return_to, "/channels"))


@router.post("/channels/{channel_id}/auto-metadata")
def toggle_channel_auto_metadata_form(
    background_tasks: BackgroundTasks,
    channel_id: int,
    return_to: str = Form("/channels", alias="next"),
    db: Session = Depends(get_db),
    section: str = Form("videos"),
):
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable")
    section = bell_section(section)
    section_label = "shorts" if section == "shorts" else "vidéos"
    enabled = toggle_channel_bell(db, channel, section)
    log_event(logger, "channel.bell", channel_id=channel.id, section=section, enabled=enabled)
    target = internal_return_path(return_to, "/channels")
    if not enabled:
        return redirect(
            append_query(
                target,
                {"message": f"Suivi quotidien des {section_label} désactivé pour {channel.name}."},
            )
        )

    job = log_job(
        db,
        "queued",
        f"Recherche automatique des nouveautés ({section_label}) de {channel.name} en file d'attente.",
        channel_id=channel.id,
    )
    background_tasks.add_task(
        run_channel_metadata_import_job, job.id, channel.id, 1, section, False
    )
    return redirect(
        append_query(
            target,
            {
                "message": f"Suivi quotidien des {section_label} activé pour {channel.name}. "
                "Synchronisation du catalogue existant lancée."
            },
        )
    )


@router.post("/channels/{channel_id}/import-metadata")
def import_channel_metadata_form(
    request: Request,
    background_tasks: BackgroundTasks,
    channel_id: int,
    page: int = Form(1),
    section: str = Form("videos"),
    return_to: str = Form("/videos", alias="next"),
    db: Session = Depends(get_db),
):
    target = internal_return_path(return_to)
    page = max(page, 1)
    channel = db.get(Channel, channel_id)
    if channel is None:
        message = "Chaîne introuvable."
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"status": "failed", "message": message}, status_code=404)
        return redirect(append_query(target, {"level": "error", "message": message}))

    section = bell_section(section)
    section_label = "shorts" if section == "shorts" else "vidéos"
    job = log_job(
        db,
        "queued",
        f"Import des métadonnées {section_label} de {channel.name} en file d'attente.",
        channel_id=channel.id,
    )
    background_tasks.add_task(run_channel_metadata_import_job, job.id, channel.id, page, section)

    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse(
            {
                "job_id": job.id,
                "status": job.status,
                "message": job.message,
                "status_url": f"/jobs/{job.id}",
                "return_to": target,
            }
        )
    return redirect(
        append_query(target, {"message": "Import des métadonnées lancé en arrière-plan."})
    )


@router.post("/channels/{channel_id}/refresh-profile")
def refresh_channel_profile_form(
    background_tasks: BackgroundTasks,
    channel_id: int,
    return_to: str = Form("/channels", alias="next"),
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable")
    background_tasks.add_task(run_channel_profile_refresh_job, channel.id)
    return redirect(
        append_query(
            internal_return_path(return_to, "/channels"),
            {"message": f"Rafraîchissement du profil de {channel.name} lancé en arrière-plan."},
        )
    )


@router.post("/channels/{channel_id}/delete")
def delete_channel_form(
    channel_id: int,
    return_to: str = Form("/channels", alias="next"),
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, channel_id)
    if channel:
        delete_channel(db, channel)
    return redirect(internal_return_path(return_to))
