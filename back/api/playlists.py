"""`/api/playlists`: reading, importing and editing playlists."""

from typing import Literal

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

from back.api.errors import error_responses
from back.api.lookups import fiche, library_playlist, playlist_item
from back.api.users import current_user_id
from back.db.session import get_db
from back.models.playlist import Playlist
from back.schemas.actions import JobQueuedRead
from back.schemas.playlist import (
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
from back.services.common.categories import parse_video_category_labels
from back.services.jobs.download_requests import InvalidMediaFormatError, queue_playlist_downloads
from back.services.jobs.downloads import run_media_download_job
from back.services.jobs.playlists import (
    PlaylistNotRefreshableError,
    queue_playlist_csv_import,
    queue_playlist_refresh,
    queue_playlist_url_import,
    run_playlist_csv_import_job,
    run_playlist_url_import_job,
)
from back.services.playlists.editing import (
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
from back.services.playlists.imports import (
    PlaylistCsvError,
    PlaylistNotFoundError,
    preview_playlist,
)
from back.services.playlists.listing import (
    list_playlists,
    load_playlist,
    playlist_csv_export,
    playlist_rows,
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


def playlist_detail_read(db: Session, playlist: Playlist) -> PlaylistDetailRead:
    rows = playlist_rows(db, playlist)
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
                url=row["video"].url,
                channel_name=row["channel_name"],
                duration_seconds=row["duration_seconds"],
                has_audio=row["has_audio"],
                has_video=row["has_video"],
                has_thumbnail=row["video"].thumbnail_path is not None,
                seen=row["seen"],
            )
            for row in rows
        ],
    )


@router.get("/playlists", response_model=list[PlaylistSummaryRead], responses=error_responses(422))
def get_playlists(
    sort: Literal["recent", "title"] = "recent",
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> list[PlaylistSummaryRead]:
    """Newest first, or by title (`sort=title`: the "add to a playlist" choices of a fiche)."""
    summaries = []
    for playlist in list_playlists(db, user_id, by_title=sort == "title"):
        summary = playlist_summary(playlist)
        cover = summary["cover_video"]
        summaries.append(
            PlaylistSummaryRead(
                **playlist_fields(playlist),
                item_count=summary["item_count"],
                cover_video_id=cover.id if cover else None,
                cover_has_thumbnail=bool(cover and cover.thumbnail_path),
            )
        )
    return summaries


@router.post(
    "/playlists", response_model=PlaylistRead, status_code=201, responses=error_responses(400, 422)
)
def create_playlist(
    payload: PlaylistCreate, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> PlaylistRead:
    try:
        playlist = create_manual_playlist(db, user_id, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist_read(playlist)


@router.post(
    "/playlists/preview", response_model=PlaylistPreviewRead, responses=error_responses(404, 422)
)
def preview(payload: PlaylistPreviewRequest, db: Session = Depends(get_db)) -> dict:
    """Summary of a playlist URL before `import-url`. Writes nothing."""
    try:
        return preview_playlist(db, payload.url)
    except PlaylistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/playlists/import-url",
    response_model=PlaylistImportRead,
    status_code=202,
    responses=error_responses(404, 422),
)
def import_url(
    payload: PlaylistUrlImport,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistImportRead:
    """Creates the playlist now; its videos (metadata only) are imported in the background."""
    try:
        playlist, job = queue_playlist_url_import(db, user_id, payload.url, payload.title)
    except PlaylistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(run_playlist_url_import_job, job.id, playlist.id)
    return PlaylistImportRead(playlist=playlist_read(playlist), job=JobQueuedRead.from_job(job))


@router.post(
    "/playlists/import-csv",
    response_model=PlaylistImportRead,
    status_code=202,
    responses=error_responses(400, 422),
)
def import_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistImportRead:
    """A Google Takeout `Vidéos de <Titre>.csv`; without `title`, the file name gives one."""
    try:
        playlist, job, rows = queue_playlist_csv_import(
            db, user_id, file.file.read(), file.filename, title
        )
    except PlaylistCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_playlist_csv_import_job, job.id, playlist.id, rows)
    return PlaylistImportRead(playlist=playlist_read(playlist), job=JobQueuedRead.from_job(job))


@router.get(
    "/playlists/{playlist_id}",
    response_model=PlaylistDetailRead,
    responses=error_responses(404, 422),
)
def get_playlist(
    playlist_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> PlaylistDetailRead:
    try:
        return playlist_detail_read(db, load_playlist(db, user_id, playlist_id))
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/playlists/{playlist_id}/export.csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "Le fichier CSV"},
        **error_responses(404, 422),
    },
)
def export_csv(
    playlist_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> Response:
    """The Google Takeout per-playlist layout, which `import-csv` reads back."""
    try:
        filename, content = playlist_csv_export(db, user_id, playlist_id)
    except PlaylistNotInLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/playlists/{playlist_id}", status_code=204, responses=error_responses(404, 422))
def remove_playlist(
    playlist_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> None:
    """Deletes the playlist, never the videos it held."""
    delete_playlist(db, library_playlist(db, user_id, playlist_id))


@router.put(
    "/playlists/{playlist_id}/title",
    response_model=PlaylistRead,
    responses=error_responses(400, 404, 422),
)
def update_title(
    playlist_id: int,
    payload: PlaylistTitleUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistRead:
    playlist = library_playlist(db, user_id, playlist_id)
    try:
        rename_playlist(db, playlist, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist_read(playlist)


@router.put(
    "/playlists/{playlist_id}/categories",
    response_model=PlaylistCategoriesRead,
    responses=error_responses(404, 422),
)
def update_categories(
    playlist_id: int,
    payload: PlaylistCategoriesUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistCategoriesRead:
    """Replaces the playlist's labels and copies them to its videos that have none."""
    playlist = library_playlist(db, user_id, playlist_id)
    labelled = set_playlist_categories(db, playlist, payload.categories)
    return PlaylistCategoriesRead(playlist=playlist_read(playlist), labelled_count=labelled)


@router.put(
    "/playlists/{playlist_id}/free-listening",
    response_model=PlaylistRead,
    responses=error_responses(404, 422),
)
def update_free_listening(
    playlist_id: int,
    payload: PlaylistFreeListeningUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistRead:
    playlist = library_playlist(db, user_id, playlist_id)
    set_free_listening(db, playlist, payload.enabled)
    return playlist_read(playlist)


@router.put(
    "/playlists/{playlist_id}/order",
    response_model=PlaylistDetailRead,
    responses=error_responses(404, 409, 422),
)
def update_order(
    playlist_id: int,
    payload: PlaylistOrderUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistDetailRead:
    """`item_ids` must hold every item of the playlist exactly; 409 if it changed meanwhile."""
    playlist = library_playlist(db, user_id, playlist_id)
    if not apply_item_order(db, playlist, payload.item_ids):
        raise HTTPException(status_code=409, detail="La playlist a changé entre-temps.")
    return playlist_detail_read(db, load_playlist(db, user_id, playlist_id))


@router.post(
    "/playlists/{playlist_id}/sort",
    response_model=PlaylistDetailRead,
    responses=error_responses(400, 404, 422),
)
def sort(
    playlist_id: int,
    payload: PlaylistSortUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistDetailRead:
    try:
        sort_playlist(db, library_playlist(db, user_id, playlist_id), payload.by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist_detail_read(db, load_playlist(db, user_id, playlist_id))


@router.post(
    "/playlists/{playlist_id}/duplicate",
    response_model=PlaylistRead,
    status_code=201,
    responses=error_responses(404, 422),
)
def duplicate(
    playlist_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> PlaylistRead:
    return playlist_read(duplicate_playlist(db, library_playlist(db, user_id, playlist_id)))


@router.post(
    "/playlists/{playlist_id}/refresh",
    response_model=JobQueuedRead,
    status_code=202,
    responses=error_responses(400, 404, 422),
)
def refresh(
    playlist_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> JobQueuedRead:
    """Imports the URL again: new videos are appended, the existing order is kept."""
    playlist = library_playlist(db, user_id, playlist_id)
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
    responses=error_responses(400, 404, 422),
)
def download_missing(
    playlist_id: int,
    media_type: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistDownloadsRead:
    playlist = library_playlist(db, user_id, playlist_id)
    try:
        queued = queue_playlist_downloads(db, playlist, media_type)
    except InvalidMediaFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for video, job in queued:
        background_tasks.add_task(run_media_download_job, job.id, video.url, media_type)
    return PlaylistDownloadsRead(jobs=[JobQueuedRead.from_job(job) for _, job in queued])


@router.post(
    "/playlists/{playlist_id}/items",
    response_model=PlaylistDetailRead,
    status_code=201,
    responses=error_responses(404, 422),
)
def add_item(
    playlist_id: int,
    payload: PlaylistItemCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistDetailRead:
    """Appends the fiche, once: adding it again changes nothing."""
    playlist = library_playlist(db, user_id, playlist_id)
    video = fiche(db, payload.video_id)
    add_video_to_playlist(db, playlist.id, video.id)
    return playlist_detail_read(db, load_playlist(db, user_id, playlist_id))


@router.delete(
    "/playlists/{playlist_id}/items/{item_id}", status_code=204, responses=error_responses(404, 422)
)
def delete_item(
    playlist_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> None:
    """Removes the item (never the fiche) and renumbers the rest."""
    remove_item(db, playlist_item(db, user_id, playlist_id, item_id))


@router.post(
    "/playlists/{playlist_id}/items/{item_id}/move",
    response_model=PlaylistDetailRead,
    responses=error_responses(404, 422),
)
def move(
    playlist_id: int,
    item_id: int,
    payload: PlaylistItemMove,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> PlaylistDetailRead:
    """Swaps the item with its neighbour; nothing at either end."""
    move_item(db, playlist_item(db, user_id, playlist_id, item_id), payload.direction)
    return playlist_detail_read(db, load_playlist(db, user_id, playlist_id))
