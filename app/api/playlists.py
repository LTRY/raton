"""`/api/playlists`: reading, importing and editing playlists.

Each route calls the service its HTML twin calls (`app/web/routes/playlists.py`).
"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.api.lookups import fiche, library_playlist, playlist_item
from app.db.session import get_db
from app.models.playlist import Playlist
from app.schemas.actions import JobQueuedRead
from app.schemas.playlist import (
    PlaylistCategoriesRead,
    PlaylistCategoriesUpdate,
    PlaylistCreate,
    PlaylistDetailRead,
    PlaylistDownloadsRead,
    PlaylistFreeListeningUpdate,
    PlaylistImportRead,
    PlaylistItemCreate,
    PlaylistItemMove,
    PlaylistItemRead,
    PlaylistOrderUpdate,
    PlaylistPreviewRead,
    PlaylistPreviewRequest,
    PlaylistRead,
    PlaylistSortUpdate,
    PlaylistStatsRead,
    PlaylistSummaryRead,
    PlaylistTitleUpdate,
    PlaylistUrlImport,
)
from app.services.common.categories import parse_video_category_labels
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
    PlaylistNotInLibraryError,
    add_video_to_playlist,
    apply_item_order,
    create_manual_playlist,
    delete_playlist,
    duplicate_playlist,
    move_item,
    remove_item,
    rename_playlist,
    set_free_listening,
    set_playlist_categories,
    sort_playlist,
)
from app.services.playlists.imports import PlaylistCsvError, PlaylistNotFoundError, preview_playlist
from app.services.playlists.listing import (
    list_playlists,
    load_playlist,
    playlist_csv_export,
    playlist_row,
    playlist_stats,
    playlist_summary,
)

router = APIRouter(prefix="/api", tags=["Playlists"])


def playlist_fields(playlist: Playlist) -> dict:
    return {
        "id": playlist.id,
        "title": playlist.title,
        "source": playlist.source,
        "source_url": playlist.source_url,
        "yt_playlist_id": playlist.yt_playlist_id,
        "categories": parse_video_category_labels(playlist.category_labels),
        "free_listening": playlist.free_listening,
        "created_at": playlist.created_at,
    }


def playlist_read(playlist: Playlist) -> PlaylistRead:
    return PlaylistRead(**playlist_fields(playlist))


def playlist_detail_read(playlist: Playlist) -> PlaylistDetailRead:
    rows = [playlist_row(item) for item in playlist.items]
    return PlaylistDetailRead(
        **playlist_fields(playlist),
        stats=PlaylistStatsRead(**playlist_stats(rows)),
        items=[
            PlaylistItemRead(
                item_id=row["item"].id,
                position=row["item"].position,
                added_at=row["item"].added_at,
                video_id=row["video"].id,
                title=row["title"],
                channel_name=row["channel_name"],
                duration_seconds=row["duration_seconds"],
                has_audio=row["has_audio"],
                has_video=row["has_video"],
                seen=row["seen"],
            )
            for row in rows
        ],
    )


@router.get("/playlists", response_model=list[PlaylistSummaryRead])
def get_playlists(db: Session = Depends(get_db)) -> list[PlaylistSummaryRead]:
    summaries = []
    for playlist in list_playlists(db):
        summary = playlist_summary(playlist)
        cover = summary["cover_video"]
        summaries.append(
            PlaylistSummaryRead(
                **playlist_fields(playlist),
                item_count=summary["item_count"],
                cover_video_id=cover.id if cover else None,
            )
        )
    return summaries


@router.post("/playlists", response_model=PlaylistRead, status_code=201)
def create_playlist(payload: PlaylistCreate, db: Session = Depends(get_db)) -> PlaylistRead:
    try:
        playlist = create_manual_playlist(db, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist_read(playlist)


@router.post("/playlists/preview", response_model=PlaylistPreviewRead)
def preview(payload: PlaylistPreviewRequest, db: Session = Depends(get_db)) -> dict:
    """Summary of a playlist URL before `import-url`. Writes nothing."""
    try:
        return preview_playlist(db, payload.url)
    except PlaylistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/playlists/import-url", response_model=PlaylistImportRead, status_code=202)
def import_url(
    payload: PlaylistUrlImport, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> PlaylistImportRead:
    """Creates the playlist now; its videos (metadata only) are imported in the background."""
    try:
        playlist, job = queue_playlist_url_import(db, payload.url, payload.title)
    except PlaylistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(run_playlist_url_import_job, job.id, playlist.id)
    return PlaylistImportRead(playlist=playlist_read(playlist), job=JobQueuedRead.from_job(job))


@router.post("/playlists/import-csv", response_model=PlaylistImportRead, status_code=202)
def import_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db),
) -> PlaylistImportRead:
    """A Google Takeout `Vidéos de <Titre>.csv`; without `title`, the file name gives one."""
    try:
        playlist, job, rows = queue_playlist_csv_import(db, file.file.read(), file.filename, title)
    except PlaylistCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_playlist_csv_import_job, job.id, playlist.id, rows)
    return PlaylistImportRead(playlist=playlist_read(playlist), job=JobQueuedRead.from_job(job))


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetailRead)
def get_playlist(playlist_id: int, db: Session = Depends(get_db)) -> PlaylistDetailRead:
    try:
        return playlist_detail_read(load_playlist(db, playlist_id))
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/playlists/{playlist_id}/export.csv")
def export_csv(playlist_id: int, db: Session = Depends(get_db)) -> Response:
    """The Google Takeout per-playlist layout, which `import-csv` reads back."""
    try:
        filename, content = playlist_csv_export(db, playlist_id)
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/playlists/{playlist_id}", status_code=204)
def remove_playlist(playlist_id: int, db: Session = Depends(get_db)) -> None:
    """Deletes the playlist, never the videos it held."""
    delete_playlist(db, library_playlist(db, playlist_id))


@router.put("/playlists/{playlist_id}/title", response_model=PlaylistRead)
def update_title(
    playlist_id: int, payload: PlaylistTitleUpdate, db: Session = Depends(get_db)
) -> PlaylistRead:
    playlist = library_playlist(db, playlist_id)
    try:
        rename_playlist(db, playlist, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist_read(playlist)


@router.put("/playlists/{playlist_id}/categories", response_model=PlaylistCategoriesRead)
def update_categories(
    playlist_id: int, payload: PlaylistCategoriesUpdate, db: Session = Depends(get_db)
) -> PlaylistCategoriesRead:
    """Replaces the playlist's labels and copies them to its videos that have none."""
    playlist = library_playlist(db, playlist_id)
    labelled = set_playlist_categories(db, playlist, payload.categories)
    return PlaylistCategoriesRead(playlist=playlist_read(playlist), labelled_count=labelled)


@router.put("/playlists/{playlist_id}/free-listening", response_model=PlaylistRead)
def update_free_listening(
    playlist_id: int, payload: PlaylistFreeListeningUpdate, db: Session = Depends(get_db)
) -> PlaylistRead:
    playlist = library_playlist(db, playlist_id)
    set_free_listening(db, playlist, payload.enabled)
    return playlist_read(playlist)


@router.put("/playlists/{playlist_id}/order", response_model=PlaylistDetailRead)
def update_order(
    playlist_id: int, payload: PlaylistOrderUpdate, db: Session = Depends(get_db)
) -> PlaylistDetailRead:
    """`item_ids` must hold every item of the playlist exactly; 409 if it changed meanwhile."""
    playlist = library_playlist(db, playlist_id)
    if not apply_item_order(db, playlist, payload.item_ids):
        raise HTTPException(status_code=409, detail="La playlist a changé entre-temps.")
    return playlist_detail_read(load_playlist(db, playlist_id))


@router.post("/playlists/{playlist_id}/sort", response_model=PlaylistDetailRead)
def sort(
    playlist_id: int, payload: PlaylistSortUpdate, db: Session = Depends(get_db)
) -> PlaylistDetailRead:
    try:
        sort_playlist(db, library_playlist(db, playlist_id), payload.by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist_detail_read(load_playlist(db, playlist_id))


@router.post("/playlists/{playlist_id}/duplicate", response_model=PlaylistRead, status_code=201)
def duplicate(playlist_id: int, db: Session = Depends(get_db)) -> PlaylistRead:
    return playlist_read(duplicate_playlist(db, library_playlist(db, playlist_id)))


@router.post("/playlists/{playlist_id}/refresh", response_model=JobQueuedRead, status_code=202)
def refresh(
    playlist_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> JobQueuedRead:
    """Imports the URL again: new videos are appended, the existing order is kept."""
    playlist = library_playlist(db, playlist_id)
    try:
        job = queue_playlist_refresh(db, playlist)
    except PlaylistNotRefreshableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_playlist_url_import_job, job.id, playlist.id)
    return JobQueuedRead.from_job(job)


@router.post(
    "/playlists/{playlist_id}/download/{media_type}",
    response_model=PlaylistDownloadsRead,
    status_code=202,
)
def download_missing(
    playlist_id: int,
    media_type: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PlaylistDownloadsRead:
    playlist = library_playlist(db, playlist_id)
    try:
        queued = queue_playlist_downloads(db, playlist, media_type)
    except InvalidMediaFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for video, job in queued:
        background_tasks.add_task(run_media_download_job, job.id, video.url, media_type)
    return PlaylistDownloadsRead(jobs=[JobQueuedRead.from_job(job) for _, job in queued])


@router.post("/playlists/{playlist_id}/items", response_model=PlaylistDetailRead, status_code=201)
def add_item(
    playlist_id: int, payload: PlaylistItemCreate, db: Session = Depends(get_db)
) -> PlaylistDetailRead:
    """Appends the fiche, once: adding it again changes nothing."""
    playlist = library_playlist(db, playlist_id)
    video = fiche(db, payload.video_id)
    add_video_to_playlist(db, playlist.id, video.id)
    return playlist_detail_read(load_playlist(db, playlist_id))


@router.delete("/playlists/{playlist_id}/items/{item_id}", status_code=204)
def delete_item(playlist_id: int, item_id: int, db: Session = Depends(get_db)) -> None:
    """Removes the item (never the fiche) and renumbers the rest."""
    remove_item(db, playlist_item(db, playlist_id, item_id))


@router.post("/playlists/{playlist_id}/items/{item_id}/move", response_model=PlaylistDetailRead)
def move(
    playlist_id: int, item_id: int, payload: PlaylistItemMove, db: Session = Depends(get_db)
) -> PlaylistDetailRead:
    """Swaps the item with its neighbour; nothing at either end."""
    move_item(db, playlist_item(db, playlist_id, item_id), payload.direction)
    return playlist_detail_read(load_playlist(db, playlist_id))
