"""Which library channel a YouTube video belongs to, and the canonical URL of a video."""

import json
from urllib.parse import quote, unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.core.config import local_media_path
from back.models.channel import Channel
from back.models.video import Video


def video_already_downloaded(db: Session, yt_video_id: str) -> bool:
    return db.scalar(select(Video.id).where(Video.yt_video_id == yt_video_id)) is not None


def canonical_video_url(video_url: str, yt_video_id: str, source_section: str = "videos") -> str:
    if source_section in {"short", "shorts"}:
        return f"https://www.youtube.com/shorts/{yt_video_id}"
    return video_url


def video_source_section(*urls: str | None) -> str:
    return "shorts" if any(url and "/shorts/" in url for url in urls) else "videos"


def channel_values_from_info(
    info: dict, fallback_url: str | None = None
) -> tuple[str | None, str | None, str | None]:
    yt_channel_id = info.get("channel_id") or info.get("uploader_id")
    url = info.get("channel_url") or info.get("uploader_url")
    name = display_channel_name_from_info(info, url, yt_channel_id)
    if not url and yt_channel_id:
        url = f"https://www.youtube.com/channel/{yt_channel_id}"
    if not url and name:
        url = f"raton:channel:{quote(str(name), safe='')}"
    if not name and fallback_url:
        name = urlparse(fallback_url).netloc or fallback_url
    return (
        str(name) if name else None,
        str(url) if url else None,
        str(yt_channel_id) if yt_channel_id else None,
    )


def looks_like_youtube_channel_id(value: object) -> bool:
    return isinstance(value, str) and value.startswith("UC") and len(value) >= 12


def channel_handle_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path_segments = [segment for segment in urlparse(str(url)).path.split("/") if segment]
    handle = next((segment for segment in path_segments if segment.startswith("@")), None)
    return unquote(handle[1:]) if handle else None


def display_channel_name_from_info(
    info: dict, url: str | None, yt_channel_id: object = None
) -> str | None:
    id_values = {
        str(value)
        for value in (
            yt_channel_id,
            info.get("channel_id"),
            info.get("uploader_id"),
            info.get("id"),
        )
        if value
    }
    for key in ("channel", "uploader", "creator", "channel_title", "uploader_name"):
        value = info.get(key)
        if not value:
            continue
        text = str(value)
        if text not in id_values and not looks_like_youtube_channel_id(text):
            return text
    return channel_handle_from_url(url)


def get_or_create_channel_from_info(
    db: Session,
    info: dict,
    fallback_url: str | None = None,
    rating: int = 0,
) -> Channel | None:
    name, url, yt_channel_id = channel_values_from_info(info, fallback_url)
    if not name or not url:
        return None
    channel = None
    if yt_channel_id:
        channel = db.scalar(select(Channel).where(Channel.yt_channel_id == yt_channel_id))
    if channel is None:
        channel = db.scalar(select(Channel).where(Channel.url == url))
    if channel:
        if not channel.yt_channel_id and yt_channel_id:
            channel.yt_channel_id = yt_channel_id
        if channel.name != name:
            channel.name = name
        return channel
    channel = Channel(url=url, name=name, yt_channel_id=yt_channel_id, rating=rating)
    db.add(channel)
    db.flush()
    return channel


def ensure_video_channel(db: Session, video: Video) -> Channel | None:
    if video.channel:
        if video.channel.category_labels and not video.category_labels:
            video.category_labels = video.channel.category_labels
            db.add(video)
            db.commit()
            db.refresh(video)
        return video.channel
    metadata = {}
    if video.metadata_path:
        path = local_media_path(video.metadata_path)
        if path.is_file():
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                metadata = {}
    channel = get_or_create_channel_from_info(db, metadata, video.url)
    if channel:
        video.channel = channel
        if channel.category_labels and not video.category_labels:
            video.category_labels = channel.category_labels
        db.add(video)
        db.commit()
        db.refresh(video)
    return channel
