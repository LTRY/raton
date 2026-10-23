from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from front.api import Api, ApiError, get_api
from front.cards import card_views, history_days, local_today, screen_time_rings
from front.formatting import category_style_map
from front.library_chat import library_chat_widget_config
from front.pages import current_request_path, page_href_builder
from front.records import record
from front.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, discussion: int | None = None, api: Api = Depends(get_api)):
    """Home: Raton's line of this visit and the library chat bar, nothing else. `?discussion=`
    opens that discussion of the chat instead of Raton (an unknown one falls back to Raton)."""
    settings = api.get("/settings")
    chat = None
    if discussion is not None:
        try:
            chat = api.get(f"/chat/conversations/{discussion}")
        except ApiError as exc:
            if exc.status != 404:
                raise
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "raton": {"scenario": record(api.post("/raton/visit"))},
            "chat_widget_config": library_chat_widget_config(
                chat or api.get("/chat"), settings["llm_provider_label"]
            ),
        },
    )


@router.get("/dashboard/nouveautes", response_class=HTMLResponse)
def dashboard_new_videos_page(request: Request, page: int = 1, api: Api = Depends(get_api)):
    nouveautes = record(api.get("/nouveautes", page=max(page, 1)))
    for stack in nouveautes.stacks:
        card_views(stack.items)
    styles = record(api.get("/categories"))
    return templates.TemplateResponse(
        request,
        "dashboard_new_videos.html",
        {
            "video_stacks": nouveautes.stacks,
            "current_new_videos_path": current_request_path(request),
            "category_style_map": category_style_map(styles),
            "page": nouveautes.page,
            "total_pages": nouveautes.total_pages,
            "page_href": page_href_builder(request),
        },
    )


@router.get("/dashboard/reprises", response_class=HTMLResponse)
def dashboard_resume_page_redirect(request: Request):
    """Old URL of the page, renamed with the section "À reprendre" -> "Historique".

    Temporary (302) rather than permanent: a 301 would stay in the browser cache even if the URL
    moved again, for no gain on a LAN app.
    """
    query = request.url.query
    return RedirectResponse(f"/dashboard/historique{'?' + query if query else ''}", status_code=302)


@router.get("/dashboard/historique", response_class=HTMLResponse)
def dashboard_history_page(request: Request, page: int = 1, api: Api = Depends(get_api)):
    history = record(api.get("/historique", page=max(page, 1)))
    styles = record(api.get("/categories"))
    return templates.TemplateResponse(
        request,
        "dashboard_history.html",
        {
            "history_days": history_days(history.rows, history.day_seconds, local_today()),
            "playback_time_stats": screen_time_rings(record(api.get("/screen-time"))),
            "category_style_map": category_style_map(styles),
            "page": history.page,
            "total_pages": history.total_pages,
            "page_href": page_href_builder(request),
        },
    )
