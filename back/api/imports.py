"""`/api/videos/import`, `/api/videos/upload`, `/api/videos/share-import`: what the import
page and the iOS share sheet bring into the library."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.db.session import get_db
from back.schemas.actions import (
    JobQueuedRead,
    ManualDownloadCreate,
    SharedVideoCreate,
    SharedVideoRead,
    UploadRead,
)
from back.services.ingest.local_upload import LocalUploadError, import_local_media
from back.services.jobs.download_requests import (
    ManualDownloadRefusedError,
    NotAYouTubeLinkError,
    import_shared_video,
    queue_manual_download,
)
from back.services.jobs.downloads import run_manual_download_job

router = APIRouter(prefix="/api", tags=["Import"])


@router.post(
    "/videos/import",
    response_model=JobQueuedRead,
    status_code=202,
    responses=error_responses(400, 422),
)
def import_video(
    payload: ManualDownloadCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobQueuedRead:
    """Download a YouTube video's formats, metadata and transcript in the background."""
    try:
        job, download = queue_manual_download(
            db,
            payload.url,
            payload.media_types,
            payload.download_transcript,
            payload.video_quality,
            payload.categories,
        )
    except ManualDownloadRefusedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_manual_download_job, job.id, *download.run_args())
    return JobQueuedRead.from_job(job)


@router.post(
    "/videos/upload",
    response_model=UploadRead,
    status_code=201,
    responses=error_responses(400, 422),
)
def upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadRead:
    """A video or audio file sent from the device; synchronous, the copy runs in the thread pool."""
    try:
        video, created = import_local_media(db, file.filename or "", file.file)
    except LocalUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UploadRead(video_id=video.id, created=created)


@router.post(
    "/videos/share-import",
    response_model=SharedVideoRead,
    responses=error_responses(400, 422, 502),
)
def share_import(payload: SharedVideoCreate, db: Session = Depends(get_db)) -> SharedVideoRead:
    """Imports a shared YouTube link now, so the caller can open the new fiche: synchronous on
    purpose (FastAPI's thread pool). `400` for a link that is not YouTube, `502` when the import
    fails (the message says why)."""
    try:
        job = import_shared_video(db, payload.url)
    except NotAYouTubeLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job.status != "downloaded" or job.video_id is None:
        raise HTTPException(status_code=502, detail=job.message)
    return SharedVideoRead(
        job_id=job.id, status=job.status, message="Import terminé.", video_id=job.video_id
    )
