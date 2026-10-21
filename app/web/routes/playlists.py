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
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.services.common.categories import parse_video_category_labels
from app.services.common.durations import format_duration
from app.services.common.settings import get_video_category_label_styles
from app.services.jobs.downloads import (
    InvalidMediaFormatError,
    queue_playlist_downloads,
    run_media_download_job,
)
from app.services.jobs.playlists import (
    PlaylistNotRefreshableError,
    queue_playlist_csv_import,
    queue_playlist_refresh,
    queue_playlist_url_import,
    run_playlist_csv_import_job,
    run_playlist_url_import_job,
)
from app.services.playlists.editing import (
    PlaylistItemNotFoundError,
    PlaylistNotInLibraryError,
    add_video_to_playlist,
    apply_item_order,
    create_manual_playlist,
    create_playlist,
    delete_playlist,
    duplicate_playlist,
    find_playlist,
    find_playlist_item,
    move_item,
    remove_item,
    rename_playlist,
    set_free_listening,
    set_playlist_categories,
    sort_playlist,
)
from app.services.playlists.imports import (
    PlaylistCsvError,
    PlaylistNotFoundError,
    preview_playlist,
)
from app.services.playlists.listing import (
    list_playlists,
    load_playlist,
    playlist_csv_export,
    playlist_row,
    playlist_stats,
    playlist_summary,
)
from app.web.formatting import format_long_duration
from app.web.shared import (
    append_query,
    category_style_map,
    form_list_values,
    form_text_value,
    internal_return_path,
    redirect,
    templates,
    wants_json,
)

router = APIRouter()


def _playlist_row(item: PlaylistItem) -> dict:
    row = playlist_row(item)
    row["duration"] = format_duration(row["duration_seconds"])
    return row


@router.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request, db: Session = Depends(get_db)):
    playlists = list_playlists(db)
    return templates.TemplateResponse(
        request,
        "playlists.html",
        {
            "playlist_summaries": [playlist_summary(playlist) for playlist in playlists],
            "message": request.query_params.get("message"),
            "message_level": request.query_params.get("level", "success"),
        },
    )


@router.post("/playlists")
def create_playlist_manual(title: str = Form(...), db: Session = Depends(get_db)):
    try:
        playlist = create_manual_playlist(db, title)
    except ValueError as exc:
        return redirect(append_query("/playlists", {"level": "error", "message": str(exc)}))
    return redirect(f"/playlists/{playlist.id}")


@router.post("/playlists/preview")
def preview_playlist_url(url: str = Form(...), db: Session = Depends(get_db)):
    """Summary of a playlist URL, shown before `import-url` is confirmed. Writes nothing."""
    try:
        info = preview_playlist(db, url)
    except PlaylistNotFoundError as exc:
        return JSONResponse({"status": "failed", "message": str(exc)}, status_code=404)
    return JSONResponse(
        {
            "status": "ok",
            **info,
            "duration_label": format_long_duration(info["duration_seconds"]),
        }
    )


@router.post("/playlists/import-url")
def import_playlist_url(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    title: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        playlist, job = queue_playlist_url_import(db, url, form_text_value(title))
    except PlaylistNotFoundError as exc:
        message = str(exc)
        if wants_json(request):
            return JSONResponse({"status": "failed", "message": message}, status_code=404)
        return redirect(append_query("/playlists", {"level": "error", "message": message}))
    background_tasks.add_task(run_playlist_url_import_job, job.id, playlist.id)

    target = f"/playlists/{playlist.id}"
    if wants_json(request):
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
        append_query(target, {"message": "Import de la playlist lancé en arrière-plan."})
    )


@router.post("/playlists/import-csv")
def import_playlist_csv(
    request: Request,
    background_tasks: BackgroundTasks,
    csv_file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        playlist, job, rows = queue_playlist_csv_import(
            db, csv_file.file.read(), csv_file.filename, form_text_value(title)
        )
    except PlaylistCsvError as exc:
        message = str(exc)
        if wants_json(request):
            return JSONResponse({"status": "failed", "message": message}, status_code=400)
        return redirect(append_query("/playlists", {"level": "error", "message": message}))
    background_tasks.add_task(run_playlist_csv_import_job, job.id, playlist.id, rows)

    target = f"/playlists/{playlist.id}"
    if wants_json(request):
        return JSONResponse(
            {
                "job_id": job.id,
                "status": job.status,
                "message": job.message,
                "status_url": f"/jobs/{job.id}",
                "return_to": target,
            }
        )
    return redirect(append_query(target, {"message": "Import du CSV lancé en arrière-plan."}))


@router.get("/playlists/{playlist_id}", response_class=HTMLResponse)
def playlist_detail_page(request: Request, playlist_id: int, db: Session = Depends(get_db)):
    try:
        playlist = load_playlist(db, playlist_id)
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rows = [_playlist_row(item) for item in playlist.items]
    stats = playlist_stats(rows)
    category_label_styles = get_video_category_label_styles(db)
    return templates.TemplateResponse(
        request,
        "playlist_detail.html",
        {
            "playlist": playlist,
            "playlist_categories": parse_video_category_labels(playlist.category_labels),
            "category_filter_options": category_label_styles,
            "category_style_map": category_style_map(category_label_styles),
            "rows": rows,
            "stats": {
                "count": stats["count"],
                "total_duration": format_long_duration(stats["total_duration_seconds"]),
                "seen_count": stats["seen_count"],
                "missing_audio": stats["missing_audio"],
                "missing_video": stats["missing_video"],
            },
            "cover_video": rows[0]["video"] if rows else None,
            "next_path": f"/playlists/{playlist.id}",
            "message": request.query_params.get("message"),
            "message_level": request.query_params.get("level", "success"),
        },
    )


@router.post("/playlists/{playlist_id}/delete")
def delete_playlist_route(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist:
        delete_playlist(db, playlist)
    return redirect(append_query("/playlists", {"message": "Playlist supprimée."}))


def _get_playlist(db: Session, playlist_id: int) -> Playlist:
    try:
        return find_playlist(db, playlist_id)
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _detail_redirect(playlist_id: int, message: str, level: str = "success"):
    return redirect(append_query(f"/playlists/{playlist_id}", {"level": level, "message": message}))


@router.post("/playlists/{playlist_id}/rename")
def rename_playlist_route(playlist_id: int, title: str = Form(...), db: Session = Depends(get_db)):
    playlist = _get_playlist(db, playlist_id)
    try:
        rename_playlist(db, playlist, form_text_value(title))
    except ValueError as exc:
        return _detail_redirect(playlist_id, str(exc), "error")
    return _detail_redirect(playlist_id, "Playlist renommée.")


@router.post("/playlists/{playlist_id}/categories")
def update_playlist_categories(
    playlist_id: int,
    preset_categories: list[str] = Form(default=[]),
    custom_categories: str = Form(""),
    db: Session = Depends(get_db),
):
    playlist = _get_playlist(db, playlist_id)
    submitted_categories = [
        *form_list_values(preset_categories),
        *parse_video_category_labels(form_text_value(custom_categories)),
    ]
    labelled = set_playlist_categories(db, playlist, submitted_categories)
    if labelled:
        message = f"Labels enregistrés, appliqués à {labelled} vidéo{'s' if labelled != 1 else ''}."
    else:
        message = "Labels enregistrés."
    return _detail_redirect(playlist_id, message)


@router.post("/playlists/{playlist_id}/free-listening")
def set_playlist_free_listening(
    request: Request, playlist_id: int, enabled: str = Form("0"), db: Session = Depends(get_db)
):
    playlist = _get_playlist(db, playlist_id)
    set_free_listening(db, playlist, enabled == "1")
    if wants_json(request):
        return JSONResponse({"status": "ok", "free_listening": playlist.free_listening})
    return redirect(f"/playlists/{playlist_id}")


@router.post("/playlists/{playlist_id}/reorder")
def reorder_playlist(
    request: Request, playlist_id: int, item_ids: str = Form(""), db: Session = Depends(get_db)
):
    playlist = _get_playlist(db, playlist_id)
    try:
        ordered = [int(value) for value in item_ids.split(",") if value.strip()]
    except ValueError:
        ordered = []
    ok = apply_item_order(db, playlist, ordered)
    if wants_json(request):
        return JSONResponse({"status": "ok" if ok else "stale"}, status_code=200 if ok else 409)
    return redirect(f"/playlists/{playlist_id}")


_SORT_LABELS = {
    "added": "date d'ajout",
    "duration": "durée",
    "title": "titre",
    "reverse": "ordre inversé",
}


@router.post("/playlists/{playlist_id}/sort")
def sort_playlist_route(playlist_id: int, by: str = Form(...), db: Session = Depends(get_db)):
    playlist = _get_playlist(db, playlist_id)
    try:
        sort_playlist(db, playlist, by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _detail_redirect(playlist_id, f"Playlist triée : {_SORT_LABELS[by]}.")


@router.post("/playlists/{playlist_id}/duplicate")
def duplicate_playlist_route(playlist_id: int, db: Session = Depends(get_db)):
    copy = duplicate_playlist(db, _get_playlist(db, playlist_id))
    return redirect(append_query(f"/playlists/{copy.id}", {"message": "Playlist dupliquée."}))


@router.get("/playlists/{playlist_id}/export.csv")
def export_playlist_csv(playlist_id: int, db: Session = Depends(get_db)):
    try:
        filename, content = playlist_csv_export(db, playlist_id)
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/playlists/{playlist_id}/refresh")
def refresh_playlist(
    playlist_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    playlist = _get_playlist(db, playlist_id)
    try:
        job = queue_playlist_refresh(db, playlist)
    except PlaylistNotRefreshableError as exc:
        return _detail_redirect(playlist_id, str(exc), "error")
    background_tasks.add_task(run_playlist_url_import_job, job.id, playlist.id)
    return _detail_redirect(playlist_id, "Rafraîchissement lancé en arrière-plan.")


@router.post("/playlists/{playlist_id}/download/{media_type}")
def download_playlist_media(
    playlist_id: int,
    media_type: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    playlist = _get_playlist(db, playlist_id)
    try:
        missing = queue_playlist_downloads(db, playlist, media_type)
    except InvalidMediaFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for video, job in missing:
        background_tasks.add_task(run_media_download_job, job.id, video.url, media_type)
    label = "audio" if media_type == "audio" else "vidéo"
    if not missing:
        return _detail_redirect(
            playlist_id, f"Toutes les {label}s de la playlist sont déjà téléchargées."
        )
    plural = "s" if len(missing) != 1 else ""
    return _detail_redirect(
        playlist_id, f"{len(missing)} téléchargement{plural} {label} lancé{plural} en arrière-plan."
    )


@router.post("/playlists/{playlist_id}/items/{item_id}/remove")
def remove_playlist_item(
    playlist_id: int,
    item_id: int,
    return_to: str = Form("", alias="next"),
    db: Session = Depends(get_db),
):
    try:
        item = find_playlist_item(db, playlist_id, item_id)
    except PlaylistItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    remove_item(db, item)
    return redirect(internal_return_path(return_to, f"/playlists/{playlist_id}"))


@router.post("/playlists/{playlist_id}/items/{item_id}/move")
def move_playlist_item(
    playlist_id: int, item_id: int, direction: str = Form(...), db: Session = Depends(get_db)
):
    try:
        item = find_playlist_item(db, playlist_id, item_id)
    except PlaylistItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    move_item(db, item, direction)
    return redirect(f"/playlists/{playlist_id}")


@router.post("/videos/{video_id}/playlists")
def add_video_to_playlist_form(
    video_id: int,
    playlist_id: str = Form(""),
    new_playlist_title: str = Form(""),
    return_to: str = Form("", alias="next"),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    target_playlist: Playlist | None = None
    new_title = form_text_value(new_playlist_title).strip()
    if new_title:
        target_playlist = create_playlist(db, new_title)
    elif playlist_id:
        target_playlist = db.get(Playlist, int(playlist_id))

    if target_playlist is not None:
        add_video_to_playlist(db, target_playlist.id, video_id)

    target = internal_return_path(return_to, f"/videos/{video_id}")
    return redirect(target)
