"""What the page of a fiche (`/videos/{id}`) shows, as data, without HTTP.

Values stay raw (seconds, counts, category keys): the route turns them into labels
(`app/web/video_detail.py`), so another client can format them its own way.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import local_media_path
from app.models.playlist import Playlist
from app.models.video import Video
from app.models.video_sponsor_segment import VideoSponsorSegment
from app.services.common.settings import get_sponsor_skip_enabled, get_video_category_label_styles
from app.services.videos.documents import read_transcript_documents, read_video_metadata
from app.services.videos.editing import mark_video_opened
from app.services.videos.playback import latest_playback_positions
from app.services.youtube.sponsor_segments import active_sponsor_segments, normalize_skip_segments


class VideoNotFoundError(ValueError):
    def __init__(self) -> None:
        super().__init__("Vidéo introuvable")


@dataclass
class VideoDetail:
    video: Video
    # `read_transcript_documents`: transcript, notes, summaries, questions, chat of the fiche.
    documents: dict
    subtitles_vtt: str | None
    # The fields of metadata.json the page shows, as yt-dlp wrote them.
    metadata: dict
    sponsor_segments: list[VideoSponsorSegment]
    sponsor_skip_enabled: bool
    # Sorted, merged and filtered segments the players skip (`normalize_skip_segments`).
    skip_segments: list[dict[str, float]]
    resume_positions: dict
    all_playlists: list[Playlist]
    category_label_styles: list[dict[str, str]]


def read_subtitles(video: Video) -> str | None:
    if not video.subtitle_path:
        return None
    subtitle_file = local_media_path(video.subtitle_path)
    if not subtitle_file.is_file():
        return None
    return subtitle_file.read_text(encoding="utf-8", errors="replace")


def detail_metadata(raw: dict) -> dict:
    return {
        "description": raw.get("description") or None,
        "tags": [tag for tag in (raw.get("tags") or []) if tag],
        "chapters": [
            {"title": chapter["title"], "start_seconds": chapter.get("start_time")}
            for chapter in (raw.get("chapters") or [])
            if isinstance(chapter, dict) and chapter.get("title")
        ],
        "duration": raw.get("duration"),
        "view_count": raw.get("view_count"),
        "like_count": raw.get("like_count"),
        "comment_count": raw.get("comment_count"),
        "uploader": raw.get("uploader") or raw.get("channel"),
    }


def find_video(db: Session, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise VideoNotFoundError()
    return video


def video_detail(db: Session, video: Video) -> VideoDetail:
    """Everything the page of a fiche shows, read only."""
    segments = active_sponsor_segments(db, video.id)
    return VideoDetail(
        video=video,
        documents=read_transcript_documents(video),
        subtitles_vtt=read_subtitles(video),
        metadata=detail_metadata(read_video_metadata(video)),
        sponsor_segments=segments,
        sponsor_skip_enabled=get_sponsor_skip_enabled(db),
        skip_segments=normalize_skip_segments(segments),
        resume_positions=latest_playback_positions(db, video.id),
        all_playlists=list(db.scalars(select(Playlist).order_by(Playlist.title))),
        category_label_styles=get_video_category_label_styles(db),
    )


def open_video_detail(db: Session, video_id: int) -> VideoDetail:
    """The page of a fiche being opened: opening it takes the fiche out of the Nouveautés."""
    video = find_video(db, video_id)
    mark_video_opened(db, video)
    return video_detail(db, video)
