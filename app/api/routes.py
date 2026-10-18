import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.models.video_sponsor_segment import VideoSponsorSegment
from app.schemas.channel import ChannelCreate, ChannelRead
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.schemas.video import VideoRead
from app.services.background_jobs import run_channel_profile_backfill_job
from app.services.channel_profile import remove_channel_profile_files
from app.services.library_charts import library_chart_data
from app.services.settings import (
    GLOBAL_QUOTA_BYTES_KEY,
    MEDIA_ROOT_KEY,
    VIDEO_CATEGORY_LABELS_KEY,
    VIDEO_LIBRARY_VIEWS_KEY,
    get_global_quota_bytes,
    get_media_root,
    get_sponsor_segment_categories,
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
    get_video_category_labels,
    get_video_library_views,
    parse_video_category_label_styles,
    parse_video_library_views,
    serialize_video_category_label_styles,
    serialize_video_category_labels,
    serialize_video_library_views,
    set_setting,
)
from app.services.sponsor_segments import normalize_skip_segments
from app.services.storage import get_total_used_bytes
from app.services.yt import ChannelNotFoundError, extract_channel_info

router = APIRouter(prefix="/api")


@router.get("/channels", response_model=list[ChannelRead])
def list_channels(db: Session = Depends(get_db)) -> list[Channel]:
    return list(db.scalars(select(Channel).order_by(Channel.name)))


@router.post("/channels", response_model=ChannelRead)
def create_channel(
    payload: ChannelCreate, db: Session = Depends(get_db), background_tasks: BackgroundTasks = None
) -> Channel:
    if payload.rating < 0 or payload.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 5")
    try:
        info = extract_channel_info(payload.url)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Channel not found") from exc
    resolved_url = info.get("url", payload.url)
    existing = db.scalar(select(Channel).where(Channel.url == resolved_url))
    if existing:
        raise HTTPException(status_code=409, detail="Channel already exists")
    channel = Channel(
        url=resolved_url,
        name=info["name"],
        yt_channel_id=info["yt_channel_id"],
        rating=payload.rating,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
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
    channel.rating = rating
    db.commit()
    db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)) -> None:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    remove_channel_profile_files(get_media_root(db), channel.yt_channel_id)
    db.delete(channel)
    db.commit()


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
    video.rating = rating
    db.commit()
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
    categories = get_sponsor_segment_categories(db)
    rows = (
        list(
            db.scalars(
                select(VideoSponsorSegment)
                .where(
                    VideoSponsorSegment.video_id == video.id,
                    VideoSponsorSegment.category.in_(categories),
                )
                .order_by(VideoSponsorSegment.start_seconds)
            )
        )
        if categories
        else []
    )
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
    if payload.media_root is not None:
        set_setting(db, MEDIA_ROOT_KEY, str(Path(payload.media_root).expanduser()))
    if payload.global_quota_bytes is not None:
        set_setting(db, GLOBAL_QUOTA_BYTES_KEY, str(payload.global_quota_bytes))
    if payload.video_category_labels is not None:
        set_setting(
            db,
            VIDEO_CATEGORY_LABELS_KEY,
            serialize_video_category_labels(payload.video_category_labels),
        )
    if payload.video_category_label_styles is not None:
        set_setting(
            db,
            VIDEO_CATEGORY_LABELS_KEY,
            serialize_video_category_label_styles(
                parse_video_category_label_styles(json.dumps(payload.video_category_label_styles))
            ),
        )
    if payload.video_library_views is not None:
        set_setting(
            db,
            VIDEO_LIBRARY_VIEWS_KEY,
            serialize_video_library_views(
                parse_video_library_views(json.dumps(payload.video_library_views))
            ),
        )
    db.commit()
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
