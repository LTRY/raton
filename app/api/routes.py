from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.channel import Channel
from app.models.video import Video
from app.schemas.channel import ChannelCreate, ChannelRead
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.schemas.video import (
    VideoDetailRead,
    VideoDocumentsRead,
    VideoMediaUrls,
    VideoMetadataRead,
    VideoPage,
    VideoPlaylistRead,
    VideoRead,
)
from app.services.channels import manage as channel_manage
from app.services.channels.manage import ChannelAlreadyInLibraryError
from app.services.common.job_log import recent_jobs
from app.services.common.ratings import InvalidRatingError, set_rating
from app.services.common.settings import (
    get_global_quota_bytes,
    get_media_root,
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
    get_video_category_labels,
    get_video_library_views,
    save_settings,
)
from app.services.jobs.backfills import run_channel_profile_backfill_job
from app.services.videos.charts import library_chart_data
from app.services.videos.detail_view import (
    VideoDetail,
    VideoNotFoundError,
    find_video,
    video_detail,
)
from app.services.videos.library_query import library_page
from app.services.videos.library_view import LIBRARY_PAGE_SIZE
from app.services.videos.stats import library_counts
from app.services.youtube.channel_info import ChannelNotFoundError
from app.services.youtube.sponsor_segments import active_sponsor_segments, normalize_skip_segments

router = APIRouter(prefix="/api")

# Error details are French, like the messages of the HTML pages and of the service exceptions.
CHANNEL_NOT_FOUND = "Chaîne introuvable"
VIDEO_NOT_FOUND = "Vidéo introuvable"


@router.get("/channels", response_model=list[ChannelRead])
def list_channels(db: Session = Depends(get_db)) -> list[Channel]:
    return list(db.scalars(select(Channel).order_by(Channel.name)))


@router.post("/channels", response_model=ChannelRead)
def create_channel(
    payload: ChannelCreate, db: Session = Depends(get_db), background_tasks: BackgroundTasks = None
) -> Channel:
    try:
        channel = channel_manage.create_channel(db, payload.url, rating=payload.rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChannelAlreadyInLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if background_tasks is not None:
        background_tasks.add_task(run_channel_profile_backfill_job)
    return channel


@router.post("/channels/{channel_id}/rating", response_model=ChannelRead)
def rate_channel(
    channel_id: int,
    rating: int = Query(..., ge=0, le=5),
    db: Session = Depends(get_db),
) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=CHANNEL_NOT_FOUND)
    set_rating(db, channel, rating)
    db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)) -> None:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=CHANNEL_NOT_FOUND)
    channel_manage.delete_channel(db, channel)


@router.get("/videos", response_model=VideoPage)
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
            video=f"/videos/{video.id}/video" if video.video_path else None,
            audio=f"/videos/{video.id}/audio" if video.audio_path else None,
            thumbnail=f"/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
            subtitles=f"/videos/{video.id}/subtitles" if video.subtitle_path else None,
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
    )


@router.get("/videos/{video_id}", response_model=VideoDetailRead)
def get_video(video_id: int, db: Session = Depends(get_db)) -> VideoDetailRead:
    """Read only: unlike the HTML page, it leaves the fiche in the Nouveautés."""
    try:
        video = find_video(db, video_id)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return video_detail_read(video_detail(db, video))


@router.post("/videos/{video_id}/rating", response_model=VideoRead)
def rate_video(
    video_id: int,
    rating: int = Query(..., ge=0, le=5),
    db: Session = Depends(get_db),
) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=VIDEO_NOT_FOUND)
    set_rating(db, video, rating)
    db.refresh(video)
    return video


@router.get("/videos/{video_id}/sponsor-segments")
def get_video_sponsor_segments(video_id: int, db: Session = Depends(get_db)) -> dict:
    """Segments à sauter pour une vidéo, déjà normalisés.

    Sert le mini-lecteur persistant de base.html : il survit aux navigations
    Turbo et se lance depuis n'importe quelle liste, donc il ne peut pas
    compter sur le bloc JSON rendu par la page détail.
    """
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=VIDEO_NOT_FOUND)
    rows = active_sponsor_segments(db, video.id)
    return {"skip_enabled": get_sponsor_skip_enabled(db), "segments": normalize_skip_segments(rows)}


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)) -> dict[str, int]:
    counts = library_counts(db)
    return {
        "channels": counts["channel_count"],
        "videos": counts["video_count"],
        "used_bytes": counts["used_bytes"],
        "quota_bytes": counts["quota_bytes"],
    }


@router.get("/stats/charts")
def get_stats_charts(db: Session = Depends(get_db)) -> dict:
    return library_chart_data(db)


@router.get("/settings", response_model=SettingsRead)
def read_settings(db: Session = Depends(get_db)) -> SettingsRead:
    return SettingsRead(
        media_root=str(get_media_root(db)),
        global_quota_bytes=get_global_quota_bytes(db),
        video_category_labels=get_video_category_labels(db),
        video_category_label_styles=get_video_category_label_styles(db),
        video_library_views=get_video_library_views(db),
    )


@router.put("/settings", response_model=SettingsRead)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsRead:
    # save_settings normalizes labels, colours and saved views itself.
    save_settings(
        db,
        media_root=str(Path(payload.media_root).expanduser())
        if payload.media_root is not None
        else None,
        global_quota_bytes=payload.global_quota_bytes,
        category_labels=payload.video_category_labels,
        category_label_styles=payload.video_category_label_styles,
        library_views=payload.video_library_views,
    )
    return read_settings(db)


@router.get("/errors")
def list_errors(db: Session = Depends(get_db)) -> list[dict[str, str | int | None]]:
    return [
        {
            "id": job.id,
            "channel_id": job.channel_id,
            "video_id": job.video_id,
            "status": job.status,
            "message": job.message,
            "created_at": job.created_at.isoformat(),
        }
        for job in recent_jobs(db)
    ]
