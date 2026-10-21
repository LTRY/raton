from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from front.api import Api, ApiError, get_api
from front.formatting import category_style_map, format_duration, format_long_duration
from front.forms import form_text_value, submitted_categories
from front.pages import append_query, internal_return_path, message_context, redirect
from front.records import record
from front.templating import templates

router = APIRouter()

SORT_LABELS = {
    "added": "date d'ajout",
    "duration": "durée",
    "title": "titre",
    "reverse": "ordre inversé",
}


def detail_redirect(playlist_id: int, message: str, level: str = "success"):
    return redirect(append_query(f"/playlists/{playlist_id}", {"level": level, "message": message}))


def refused(exc: ApiError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


@router.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request, api: Api = Depends(get_api)):
    return templates.TemplateResponse(
        request,
        "playlists.html",
        {"playlist_summaries": record(api.get("/playlists")), **message_context(request)},
    )


@router.post("/playlists")
def create_playlist_manual(title: str = Form(...), api: Api = Depends(get_api)):
    try:
        playlist = api.post("/playlists", {"title": title})
    except ApiError as exc:
        return redirect(append_query("/playlists", {"level": "error", "message": exc.detail}))
    return redirect(f"/playlists/{playlist['id']}")


@router.post("/playlists/import-url")
def import_playlist_url(url: str = Form(...), title: str = Form(""), api: Api = Depends(get_api)):
    """The no-JS fallback of the URL import, which app.js sends to /api."""
    try:
        queued = api.post("/playlists/import-url", {"url": url, "title": form_text_value(title)})
    except ApiError as exc:
        return redirect(append_query("/playlists", {"level": "error", "message": exc.detail}))
    return redirect(
        append_query(
            f"/playlists/{queued['playlist']['id']}",
            {"message": "Import de la playlist lancé en arrière-plan."},
        )
    )


@router.post("/playlists/import-csv")
def import_playlist_csv(
    file: UploadFile = File(...), title: str = Form(""), api: Api = Depends(get_api)
):
    """The no-JS fallback of the CSV import, which app.js sends to /api."""
    try:
        queued = api.post(
            "/playlists/import-csv",
            files={"file": (file.filename or "playlist.csv", file.file.read())},
            data={"title": form_text_value(title)},
        )
    except ApiError as exc:
        return redirect(append_query("/playlists", {"level": "error", "message": exc.detail}))
    return redirect(
        append_query(
            f"/playlists/{queued['playlist']['id']}",
            {"message": "Import du CSV lancé en arrière-plan."},
        )
    )


@router.get("/playlists/{playlist_id}", response_class=HTMLResponse)
def playlist_detail_page(request: Request, playlist_id: int, api: Api = Depends(get_api)):
    playlist = record(api.get(f"/playlists/{playlist_id}"))
    styles = record(api.get("/categories"))
    for row in playlist.items:
        row.duration = format_duration(row.duration_seconds)
    stats = playlist.stats
    return templates.TemplateResponse(
        request,
        "playlist_detail.html",
        {
            "playlist": playlist,
            "playlist_categories": playlist.categories,
            "category_filter_options": styles,
            "category_style_map": category_style_map(styles),
            "rows": playlist.items,
            "stats": {
                "count": stats.count,
                "total_duration": format_long_duration(stats.total_duration_seconds),
                "seen_count": stats.seen_count,
                "missing_audio": stats.missing_audio,
                "missing_video": stats.missing_video,
            },
            **message_context(request),
        },
    )


@router.post("/playlists/{playlist_id}/delete")
def delete_playlist_route(playlist_id: int, api: Api = Depends(get_api)):
    try:
        api.delete(f"/playlists/{playlist_id}")
    except ApiError as exc:
        if exc.status != 404:
            raise
    return redirect(append_query("/playlists", {"message": "Playlist supprimée."}))


@router.post("/playlists/{playlist_id}/rename")
def rename_playlist_route(playlist_id: int, title: str = Form(...), api: Api = Depends(get_api)):
    try:
        api.put(f"/playlists/{playlist_id}/title", {"title": form_text_value(title)})
    except ApiError as exc:
        if exc.status == 404:
            raise
        return detail_redirect(playlist_id, exc.detail, "error")
    return detail_redirect(playlist_id, "Playlist renommée.")


@router.post("/playlists/{playlist_id}/categories")
def update_playlist_categories(
    playlist_id: int,
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    api: Api = Depends(get_api),
):
    labelled = api.put(
        f"/playlists/{playlist_id}/categories",
        {"categories": submitted_categories(preset_categories, custom_categories)},
    )["labelled_count"]
    if labelled:
        message = f"Labels enregistrés, appliqués à {labelled} vidéo{'s' if labelled != 1 else ''}."
    else:
        message = "Labels enregistrés."
    return detail_redirect(playlist_id, message)


@router.post("/playlists/{playlist_id}/free-listening")
def set_playlist_free_listening(
    playlist_id: int, enabled: str = Form("0"), api: Api = Depends(get_api)
):
    """The no-JS fallback of the switch, which playlist-player.js saves with PUT /api/..."""
    api.put(f"/playlists/{playlist_id}/free-listening", {"enabled": enabled == "1"})
    return redirect(f"/playlists/{playlist_id}")


@router.post("/playlists/{playlist_id}/sort")
def sort_playlist_route(playlist_id: int, by: str = Form(...), api: Api = Depends(get_api)):
    try:
        api.post(f"/playlists/{playlist_id}/sort", {"by": by})
    except ApiError as exc:
        raise refused(exc) from exc
    return detail_redirect(playlist_id, f"Playlist triée : {SORT_LABELS[by]}.")


@router.post("/playlists/{playlist_id}/duplicate")
def duplicate_playlist_route(playlist_id: int, api: Api = Depends(get_api)):
    copy = api.post(f"/playlists/{playlist_id}/duplicate")
    return redirect(append_query(f"/playlists/{copy['id']}", {"message": "Playlist dupliquée."}))


@router.get("/playlists/{playlist_id}/export.csv")
def export_playlist_csv(playlist_id: int, api: Api = Depends(get_api)):
    exported = api.request("GET", f"/playlists/{playlist_id}/export.csv")
    return Response(
        exported.content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": exported.headers["content-disposition"]},
    )


@router.post("/playlists/{playlist_id}/refresh")
def refresh_playlist(playlist_id: int, api: Api = Depends(get_api)):
    try:
        api.post(f"/playlists/{playlist_id}/refresh")
    except ApiError as exc:
        if exc.status == 404:
            raise
        return detail_redirect(playlist_id, exc.detail, "error")
    return detail_redirect(playlist_id, "Rafraîchissement lancé en arrière-plan.")


@router.post("/playlists/{playlist_id}/download/{media_type}")
def download_playlist_media(playlist_id: int, media_type: str, api: Api = Depends(get_api)):
    try:
        missing = api.post(f"/playlists/{playlist_id}/download/{media_type}")["jobs"]
    except ApiError as exc:
        raise refused(exc) from exc
    label = "audio" if media_type == "audio" else "vidéo"
    if not missing:
        return detail_redirect(
            playlist_id, f"Toutes les {label}s de la playlist sont déjà téléchargées."
        )
    plural = "s" if len(missing) != 1 else ""
    return detail_redirect(
        playlist_id, f"{len(missing)} téléchargement{plural} {label} lancé{plural} en arrière-plan."
    )


@router.post("/playlists/{playlist_id}/items/{item_id}/remove")
def remove_playlist_item(
    playlist_id: int,
    item_id: int,
    return_to: str = Form("", alias="next"),
    api: Api = Depends(get_api),
):
    api.delete(f"/playlists/{playlist_id}/items/{item_id}")
    return redirect(internal_return_path(return_to, f"/playlists/{playlist_id}"))


@router.post("/playlists/{playlist_id}/items/{item_id}/move")
def move_playlist_item(
    playlist_id: int, item_id: int, direction: str = Form(...), api: Api = Depends(get_api)
):
    api.post(f"/playlists/{playlist_id}/items/{item_id}/move", {"direction": direction})
    return redirect(f"/playlists/{playlist_id}")


@router.post("/videos/{video_id}/playlists")
def add_video_to_playlist_form(
    video_id: int,
    playlist_id: str = Form(""),
    new_playlist_title: str = Form(""),
    return_to: str = Form("", alias="next"),
    api: Api = Depends(get_api),
):
    """From a fiche: adds it to an existing playlist, or to a new one named in the form."""
    new_title = form_text_value(new_playlist_title).strip()
    target_id = api.post("/playlists", {"title": new_title})["id"] if new_title else playlist_id
    if target_id:
        api.post(f"/playlists/{target_id}/items", {"video_id": video_id})
    return redirect(internal_return_path(return_to, f"/videos/{video_id}"))
