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
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.playlist import Playlist, PlaylistItem
from app.models.video import Video
from app.services.common.categories import parse_video_category_labels
from app.services.common.durations import format_duration
from app.services.common.job_log import log_job
from app.services.common.settings import get_video_category_label_styles
from app.services.jobs.downloads import run_manual_download_job
from app.services.playlists.editing import (
    add_video_to_playlist,
    apply_item_order,
    create_playlist,
    delete_playlist,
    duplicate_playlist,
    move_item,
    playlist_title_from_filename,
    remove_item,
    rename_playlist,
    set_free_listening,
    set_playlist_categories,
    sort_playlist,
    videos_missing_media,
)
from app.services.playlists.imports import (
    PlaylistCsvError,
    PlaylistNotFoundError,
    extract_playlist_info,
    parse_playlist_csv,
    playlist_to_csv,
    preview_playlist,
    run_playlist_csv_import_job,
    run_playlist_url_import_job,
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


def _playlist_summary(playlist: Playlist) -> dict:
    first_item = playlist.items[0] if playlist.items else None
    return {
        "playlist": playlist,
        "item_count": len(playlist.items),
        "cover_video": first_item.video if first_item else None,
    }


def _playlist_row(item: PlaylistItem) -> dict:
    video = item.video
    # The column, not metadata.json: a playlist can hold hundreds of videos and the file is a ~140 KB dump.
    seconds = video.duration_seconds or 0
    return {
        "item": item,
        "video": video,
        "title": video.title,
        "channel_name": video.channel.name if video.channel else None,
        "duration": format_duration(seconds),
        "duration_seconds": seconds,
        "has_audio": bool(video.audio_path),
        "has_video": bool(video.video_path),
        # watched_at is set by the 90% rule and cleared when the media is purged.
        "seen": video.watched_at is not None,
    }


@router.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request, db: Session = Depends(get_db)):
    playlists = list(
        db.scalars(
            select(Playlist)
            .options(selectinload(Playlist.items))
            .order_by(Playlist.created_at.desc())
        )
    )
    # One query for every cover: the lazy `item.video` loads then hit the session's identity map.
    cover_ids = [playlist.items[0].video_id for playlist in playlists if playlist.items]
    if cover_ids:
        list(db.scalars(select(Video).where(Video.id.in_(cover_ids))))
    return templates.TemplateResponse(
        request,
        "playlists.html",
        {
            "playlist_summaries": [_playlist_summary(playlist) for playlist in playlists],
            "message": request.query_params.get("message"),
            "message_level": request.query_params.get("level", "success"),
        },
    )


@router.post("/playlists")
def create_playlist_manual(title: str = Form(...), db: Session = Depends(get_db)):
    title = title.strip()
    if not title:
        return redirect(
            append_query("/playlists", {"level": "error", "message": "Le titre est obligatoire."})
        )
    playlist = create_playlist(db, title)
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
        info = extract_playlist_info(url)
    except PlaylistNotFoundError as exc:
        message = str(exc)
        if wants_json(request):
            return JSONResponse({"status": "failed", "message": message}, status_code=404)
        return redirect(append_query("/playlists", {"level": "error", "message": message}))

    playlist = create_playlist(
        db,
        form_text_value(title) or info["title"],
        source="url",
        source_url=info["url"],
        yt_playlist_id=info.get("yt_playlist_id"),
    )

    job = log_job(db, "queued", f"Import de la playlist {playlist.title} en file d'attente.")
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
        rows = parse_playlist_csv(csv_file.file.read())
    except PlaylistCsvError as exc:
        message = str(exc)
        if wants_json(request):
            return JSONResponse({"status": "failed", "message": message}, status_code=400)
        return redirect(append_query("/playlists", {"level": "error", "message": message}))

    playlist_title = form_text_value(title) or playlist_title_from_filename(
        csv_file.filename or "Playlist importée"
    )
    playlist = create_playlist(db, playlist_title, source="csv")

    job = log_job(db, "queued", f"Import de la playlist {playlist.title} en file d'attente.")
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
    playlist = db.scalars(
        select(Playlist)
        .where(Playlist.id == playlist_id)
        .options(
            selectinload(Playlist.items)
            .selectinload(PlaylistItem.video)
            .selectinload(Video.channel)
        )
    ).one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist introuvable")

    rows = [_playlist_row(item) for item in playlist.items]
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
                "count": len(rows),
                "total_duration": format_long_duration(
                    sum(row["duration_seconds"] for row in rows)
                ),
                "seen_count": sum(1 for row in rows if row["seen"]),
                "missing_audio": sum(1 for row in rows if not row["has_audio"]),
                "missing_video": sum(1 for row in rows if not row["has_video"]),
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
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    return playlist


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
    playlist = _get_playlist(db, playlist_id)
    return Response(
        playlist_to_csv(playlist),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="playlist-{playlist.id}.csv"'},
    )


@router.post("/playlists/{playlist_id}/refresh")
def refresh_playlist(
    playlist_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    playlist = _get_playlist(db, playlist_id)
    if playlist.source != "url" or not playlist.source_url:
        return _detail_redirect(
            playlist_id, "Seule une playlist importée depuis une URL peut être rafraîchie.", "error"
        )
    job = log_job(db, "queued", f"Import de la playlist {playlist.title} en file d'attente.")
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
    if media_type not in {"audio", "video"}:
        raise HTTPException(status_code=400, detail="Le format doit être vidéo ou audio.")
    missing = videos_missing_media(playlist, media_type)
    for video in missing:
        job = log_job(db, "queued", "Téléchargement en file d'attente.", video_id=video.id)
        background_tasks.add_task(
            run_manual_download_job, job.id, video.url, [media_type, "metadata"], False
        )
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
    item = db.get(PlaylistItem, item_id)
    if item is None or item.playlist_id != playlist_id:
        raise HTTPException(status_code=404, detail="Élément introuvable")
    remove_item(db, item)
    return redirect(internal_return_path(return_to, f"/playlists/{playlist_id}"))


@router.post("/playlists/{playlist_id}/items/{item_id}/move")
def move_playlist_item(
    playlist_id: int, item_id: int, direction: str = Form(...), db: Session = Depends(get_db)
):
    item = db.get(PlaylistItem, item_id)
    if item is None or item.playlist_id != playlist_id:
        raise HTTPException(status_code=404, detail="Élément introuvable")
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
