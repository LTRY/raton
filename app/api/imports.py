"""`/api/videos/import` and `/api/videos/upload`: what the import page brings into the library.

Each route calls the service its HTML twin calls (`app/web/routes/videos.py`).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.session import get_db
from app.schemas.actions import JobQueuedRead, ManualDownloadCreate, UploadRead
from app.services.ingest.local_upload import LocalUploadError, import_local_media
from app.services.jobs.download_requests import ManualDownloadRefusedError, queue_manual_download
from app.services.jobs.downloads import run_manual_download_job

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
