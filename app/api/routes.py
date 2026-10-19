import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.schemas.channel import ChannelCreate, ChannelRead
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.schemas.video import VideoRead
from app.services.channels import manage as channel_manage
from app.services.channels.manage import ChannelAlreadyInLibraryError
from app.services.common.categories import (
    parse_video_category_label_styles,
)
from app.services.common.library_views import (
    parse_video_library_views,
)
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
from app.services.media.storage import get_total_used_bytes
from app.services.videos.charts import library_chart_data
from app.services.youtube.channel_info import ChannelNotFoundError
from app.services.youtube.sponsor_segments import active_sponsor_segments, normalize_skip_segments

router = APIRouter(prefix="/api")


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
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 5") from exc
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Channel not found") from exc
    except ChannelAlreadyInLibraryError as exc:
        raise HTTPException(status_code=409, detail="Channel already exists") from exc
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
        raise HTTPException(status_code=404, detail="Channel not found")
    set_rating(db, channel, rating)
    db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)) -> None:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel_manage.delete_channel(db, channel)


@router.get("/videos", response_model=list[VideoRead])
def list_videos(channel_id: int | None = None, db: Session = Depends(get_db)) -> list[Video]:
    query = select(Video).order_by(desc(Video.downloaded_at), desc(Video.id))
    if channel_id:
        query = query.where(Video.channel_id == channel_id)
    return list(db.scalars(query))


@router.post("/videos/{video_id}/rating", response_model=VideoRead)
def rate_video(
    video_id: int,
    rating: int = Query(..., ge=0, le=5),
    db: Session = Depends(get_db),
) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
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
        raise HTTPException(status_code=404, detail="Vidéo introuvable")
    rows = active_sponsor_segments(db, video.id)
    return {"skip_enabled": get_sponsor_skip_enabled(db), "segments": normalize_skip_segments(rows)}


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)) -> dict[str, int]:
    return {
        "channels": db.scalar(select(func.count(Channel.id))) or 0,
        "videos": db.scalar(select(func.count(Video.id))) or 0,
        "used_bytes": get_total_used_bytes(db),
        "quota_bytes": get_global_quota_bytes(db),
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
    label_styles = (
        parse_video_category_label_styles(json.dumps(payload.video_category_label_styles))
        if payload.video_category_label_styles is not None
        else None
    )
    save_settings(
        db,
        media_root=str(Path(payload.media_root).expanduser())
        if payload.media_root is not None
        else None,
        global_quota_bytes=payload.global_quota_bytes,
        category_labels=payload.video_category_labels,
        category_label_styles=label_styles,
        library_views=(
            parse_video_library_views(json.dumps(payload.video_library_views))
            if payload.video_library_views is not None
            else None
        ),
    )
    return read_settings(db)


@router.get("/errors")
def list_errors(db: Session = Depends(get_db)) -> list[dict[str, str | int | None]]:
    jobs = db.scalars(select(DownloadJob).order_by(desc(DownloadJob.created_at)).limit(100))
    return [
        {
            "id": job.id,
            "channel_id": job.channel_id,
            "video_id": job.video_id,
            "status": job.status,
            "message": job.message,
            "created_at": job.created_at.isoformat(),
        }
        for job in jobs
    ]
