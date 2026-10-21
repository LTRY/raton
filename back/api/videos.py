"""`/api/videos`: reading a fiche or a page of them, and the actions on a fiche.

The library list with its filters is `/api/library`, the LLM requests on a fiche are in
`llm.py`, its files in `media.py`.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import true
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.api.lookups import fiche
from back.db.session import get_db
from back.models.video import Video
from back.schemas.actions import (
    CategoriesUpdate,
    CommentUpdate,
    JobQueuedRead,
    ListStateUpdate,
    MediaDownload,
    PlaybackActivity,
    SkipSegmentsRead,
    SponsorSegmentsFetchRead,
    VideoStateRead,
)
from back.schemas.channel import RatingUpdate
from back.schemas.video import (
    VideoChannelRead,
    VideoDetailRead,
    VideoDocumentsRead,
    VideoMediaUrls,
    VideoMetadataRead,
    VideoPage,
    VideoPlaylistRead,
    VideoRead,
)
from back.services.common.categories import parse_video_category_labels
from back.services.common.ratings import InvalidRatingError, set_rating
from back.services.common.settings import (
    get_sponsor_skip_enabled,
)
from back.services.jobs.download_requests import (
    InvalidMediaFormatError,
    queue_media_download,
    queue_transcript_retry,
)
from back.services.jobs.downloads import run_media_download_job, run_transcript_retry_job
from back.services.media.media_storage import delete_video_media_file
from back.services.videos.detail_view import (
    VideoDetail,
    video_detail,
)
from back.services.videos.editing import (
    mark_video_opened,
    set_video_categories,
    set_video_comment,
    set_video_list_state,
)
from back.services.videos.filters import video_badges
from back.services.videos.library_query import library_page
from back.services.videos.library_view import LIBRARY_PAGE_SIZE
from back.services.videos.playback import InvalidPlaybackMediaError, record_playback_activity
from back.services.youtube.sponsor_segments import (
    SponsorSegmentsFetchError,
    active_sponsor_segments,
    normalize_skip_segments,
    refresh_sponsor_segments,
)

router = APIRouter(prefix="/api", tags=["Fiches"])


@router.get("/videos", response_model=VideoPage, responses=error_responses(422))
def list_videos(
    channel_id: int | None = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> VideoPage:
    where = Video.channel_id == channel_id if channel_id else true()
    videos, page, total_pages, total = library_page(
        db, where, "imported", "", page, LIBRARY_PAGE_SIZE
    )
    return VideoPage(
        items=[VideoRead.model_validate(video) for video in videos],
        page=page,
        total_pages=total_pages,
        total=total,
    )


def video_detail_read(detail: VideoDetail) -> VideoDetailRead:
    video = detail.video
    metadata = detail.metadata
    documents = detail.documents
    return VideoDetailRead(
        **VideoRead.model_validate(video).model_dump(),
        is_new=video.is_new,
        list_state=video.list_state,
        comment=video.comment,
        duration_seconds=video.duration_seconds,
        watched_at=video.watched_at,
        # Both paths can be set at once: check each column, never media_type.
        media_urls=VideoMediaUrls(
            video=f"/api/videos/{video.id}/video" if video.video_path else None,
            audio=f"/api/videos/{video.id}/audio" if video.audio_path else None,
            thumbnail=f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
            subtitles=f"/api/videos/{video.id}/subtitles" if video.subtitle_path else None,
        ),
        metadata=VideoMetadataRead(
            description=metadata["description"],
            tags=metadata["tags"],
            chapters=metadata["chapters"],
            duration_seconds=metadata["duration"],
            view_count=metadata["view_count"],
            like_count=metadata["like_count"],
            comment_count=metadata["comment_count"],
            uploader=metadata["uploader"],
        ),
        documents=VideoDocumentsRead.from_documents(documents),
        sponsor_segments=detail.sponsor_segments,
        sponsor_skip_enabled=detail.sponsor_skip_enabled,
        skip_segments=detail.skip_segments,
        resume_positions=detail.resume_positions,
        playlists=[
            VideoPlaylistRead(
                playlist_id=item.playlist_id, title=item.playlist.title, item_id=item.id
            )
            for item in video.playlist_items
        ],
        channel=VideoChannelRead(id=video.channel.id, name=video.channel.name)
        if video.channel
        else None,
        badges=video_badges(video),
        has_transcript=video.transcript_path is not None,
        subtitles_vtt=detail.subtitles_vtt,
    )


@router.get(
    "/videos/{video_id}", response_model=VideoDetailRead, responses=error_responses(404, 422)
)
def get_video(video_id: int, db: Session = Depends(get_db)) -> VideoDetailRead:
    """Read only: unlike the HTML page, it leaves the fiche in the Nouveautés."""
    return video_detail_read(video_detail(db, fiche(db, video_id)))


@router.get(
    "/videos/{video_id}/sponsor-segments",
    response_model=SkipSegmentsRead,
    responses=error_responses(404, 422),
)
def get_video_sponsor_segments(video_id: int, db: Session = Depends(get_db)) -> SkipSegmentsRead:
    """The segments to skip, normalized, for the persistent mini player of base.html.

    It survives Turbo navigations and starts from any list, so it cannot rely on the JSON block
    the fiche's page renders.
    """
    video = fiche(db, video_id)
    rows = active_sponsor_segments(db, video.id)
    return SkipSegmentsRead(
        skip_enabled=get_sponsor_skip_enabled(db), segments=normalize_skip_segments(rows)
    )


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


@router.post(
    "/videos/{video_id}/open", response_model=VideoStateRead, responses=error_responses(404, 422)
)
def open_video(video_id: int, db: Session = Depends(get_db)) -> VideoStateRead:
    """What opening the fiche's page does: takes it out of the Nouveautés."""
    video = fiche(db, video_id)
    mark_video_opened(db, video)
    return video_state(video)


@router.put(
    "/videos/{video_id}/rating",
    response_model=VideoStateRead,
    responses=error_responses(400, 404, 422),
)
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


@router.put(
    "/videos/{video_id}/list-state",
    response_model=VideoStateRead,
    responses=error_responses(400, 404, 422),
)
def update_list_state(
    video_id: int, payload: ListStateUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    video = fiche(db, video_id)
    try:
        set_video_list_state(db, video, payload.state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return video_state(video)


@router.put(
    "/videos/{video_id}/categories",
    response_model=VideoStateRead,
    responses=error_responses(404, 422),
)
def update_categories(
    video_id: int, payload: CategoriesUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    video = fiche(db, video_id)
    set_video_categories(db, video, payload.categories)
    return video_state(video)


@router.put(
    "/videos/{video_id}/comment", response_model=VideoStateRead, responses=error_responses(404, 422)
)
def update_comment(
    video_id: int, payload: CommentUpdate, db: Session = Depends(get_db)
) -> VideoStateRead:
    video = fiche(db, video_id)
    set_video_comment(db, video, payload.comment)
    return video_state(video)


@router.post(
    "/videos/{video_id}/activity",
    response_model=VideoStateRead,
    responses=error_responses(400, 404, 422),
)
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
    responses=error_responses(400, 404, 422),
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


@router.delete(
    "/videos/{video_id}/media/{media_type}",
    status_code=204,
    responses=error_responses(400, 404, 422),
)
def delete_media(video_id: int, media_type: str, db: Session = Depends(get_db)) -> None:
    video = fiche(db, video_id)
    try:
        delete_video_media_file(db, video, media_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/videos/{video_id}/transcript/download",
    response_model=JobQueuedRead,
    status_code=202,
    responses=error_responses(404, 422),
)
def retry_transcript(
    video_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> JobQueuedRead:
    video = fiche(db, video_id)
    job = queue_transcript_retry(db, video)
    background_tasks.add_task(run_transcript_retry_job, job.id, video.id)
    return JobQueuedRead.from_job(job)


@router.post(
    "/videos/{video_id}/sponsor-segments/fetch",
    response_model=SponsorSegmentsFetchRead,
    responses=error_responses(404, 422, 502),
)
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
