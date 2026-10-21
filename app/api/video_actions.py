"""`/api` actions on a fiche and the status of the jobs they start.

Each route calls the service its HTML form twin calls (`app/web/routes/videos.py`, `media.py`).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.video import Video
from app.schemas.actions import (
    CategoriesUpdate,
    CommentUpdate,
    JobQueuedRead,
    JobStatusRead,
    ListStateUpdate,
    MediaDownload,
    PlaybackActivity,
    RecentJobRead,
    SponsorSegmentsFetchRead,
    VideoStateRead,
)
from app.schemas.channel import RatingUpdate
from app.services.common.categories import parse_video_category_labels
from app.services.common.job_log import JOB_DONE_STATUSES, recent_jobs
from app.services.common.ratings import InvalidRatingError, set_rating
from app.services.common.settings import get_sponsor_skip_enabled
from app.services.jobs.downloads import (
    InvalidMediaFormatError,
    JobNotFoundError,
    job_status,
    queue_media_download,
    queue_transcript_retry,
    run_media_download_job,
    run_transcript_retry_job,
)
from app.services.media.media_storage import delete_video_media_file
from app.services.videos.detail_view import VideoNotFoundError, find_video
from app.services.videos.editing import (
    mark_video_opened,
    set_video_categories,
    set_video_comment,
    set_video_list_state,
)
from app.services.videos.playback import InvalidPlaybackMediaError, record_playback_activity
from app.services.youtube.sponsor_segments import (
    SponsorSegmentsFetchError,
    active_sponsor_segments,
    normalize_skip_segments,
    refresh_sponsor_segments,
)

router = APIRouter(prefix="/api")


def fiche(db: Session, video_id: int) -> Video:
    try:
        return find_video(db, video_id)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def video_state(video: Video) -> VideoStateRead:
    return VideoStateRead(
        id=video.id,
        is_new=video.is_new,
        list_state=video.list_state,
        rating=video.rating,
        categories=parse_video_category_labels(video.category_labels),
        comment=video.comment,
        watched_at=video.watched_at,
    )


@router.post("/videos/{video_id}/open", response_model=VideoStateRead)
def open_video(video_id: int, db: Session = Depends(get_db)) -> VideoStateRead:
    """What opening the fiche's page does: takes it out of the Nouveautés."""
    video = fiche(db, video_id)
    mark_video_opened(db, video)
    return video_state(video)


@router.put("/videos/{video_id}/rating", response_model=VideoStateRead)
def update_rating(
    video_id: int, payload: RatingUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    """0 to 5 stars; 400 with the service's message otherwise."""
    video = fiche(db, video_id)
    try:
        set_rating(db, video, payload.rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return video_state(video)


@router.put("/videos/{video_id}/list-state", response_model=VideoStateRead)
def update_list_state(
    video_id: int, payload: ListStateUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    video = fiche(db, video_id)
    try:
        set_video_list_state(db, video, payload.state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return video_state(video)


@router.put("/videos/{video_id}/categories", response_model=VideoStateRead)
def update_categories(
    video_id: int, payload: CategoriesUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    video = fiche(db, video_id)
    set_video_categories(db, video, payload.categories)
    return video_state(video)


@router.put("/videos/{video_id}/comment", response_model=VideoStateRead)
def update_comment(
    video_id: int, payload: CommentUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    video = fiche(db, video_id)
    set_video_comment(db, video, payload.comment)
    return video_state(video)


@router.post("/videos/{video_id}/activity", response_model=VideoStateRead)
def log_activity(
    video_id: int, payload: PlaybackActivity, db: Session = Depends(get_db)
) -> VideoStateRead:
    """A playback report of a player; may mark the fiche Vu (`mark_watched_if_complete`)."""
    video = fiche(db, video_id)
    try:
        record_playback_activity(
            db,
            video,
            payload.media_type,
            payload.position_seconds,
            payload.duration_seconds,
            payload.watched_seconds,
        )
    except InvalidPlaybackMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return video_state(video)


@router.post(
    "/videos/{video_id}/media/{media_type}/download",
    response_model=JobQueuedRead,
    status_code=202,
)
def download_media(
    video_id: int,
    media_type: str,
    background_tasks: BackgroundTasks,
    payload: MediaDownload | None = None,
    db: Session = Depends(get_db),
) -> JobQueuedRead:
    video = fiche(db, video_id)
    video_quality = payload.video_quality if payload else "1080"
    try:
        job = queue_media_download(db, video, media_type, video_quality)
    except InvalidMediaFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_media_download_job, job.id, video.url, media_type, video_quality)
    return JobQueuedRead.from_job(job)


@router.delete("/videos/{video_id}/media/{media_type}", status_code=204)
def delete_media(video_id: int, media_type: str, db: Session = Depends(get_db)) -> None:
    video = fiche(db, video_id)
    try:
        delete_video_media_file(db, video, media_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/videos/{video_id}/transcript/download", response_model=JobQueuedRead, status_code=202
)
def retry_transcript(
    video_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> JobQueuedRead:
    video = fiche(db, video_id)
    job = queue_transcript_retry(db, video)
    background_tasks.add_task(run_transcript_retry_job, job.id, video.id)
    return JobQueuedRead.from_job(job)


@router.post("/videos/{video_id}/sponsor-segments/fetch", response_model=SponsorSegmentsFetchRead)
def fetch_sponsor_segments(
    video_id: int, db: Session = Depends(get_db)
) -> SponsorSegmentsFetchRead:
    """Ask SponsorBlock again; answers the segments to skip, as `GET .../sponsor-segments` does."""
    video = fiche(db, video_id)
    try:
        rows = refresh_sponsor_segments(db, video)
    except SponsorSegmentsFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SponsorSegmentsFetchRead(
        count=len(rows),
        skip_enabled=get_sponsor_skip_enabled(db),
        segments=normalize_skip_segments(active_sponsor_segments(db, video.id)),
    )


@router.get("/jobs", response_model=list[RecentJobRead])
def list_jobs(
    status: list[str] = Query(default=[]), db: Session = Depends(get_db)
) -> list[RecentJobRead]:
    """The 100 latest jobs, newest first; `status` (repeatable) keeps only those statuses."""
    return [
        RecentJobRead(
            id=job.id,
            status=job.status,
            message=job.message,
            channel_id=job.channel_id,
            video_id=job.video_id,
            created_at=job.created_at,
            done=job.status in JOB_DONE_STATUSES,
        )
        for job in recent_jobs(db, statuses=status)
    ]


@router.get("/jobs/{job_id}", response_model=JobStatusRead, response_model_exclude_none=True)
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return job_status(db, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
