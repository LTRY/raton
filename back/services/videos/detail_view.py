"""What the page of a fiche (`/videos/{id}`) shows, as data, without HTTP.

Values stay raw (seconds, counts, category keys): `GET /api/videos/{id}` sends them as they
are, and each client formats them its own way.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from back.core.config import local_media_path
from back.models.playlist import Playlist
from back.models.user import UserVideo
from back.models.video import Video
from back.models.video_sponsor_segment import VideoSponsorSegment
from back.services.common.settings import (
    get_no_progress_category_labels,
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
)
from back.services.common.user_state import video_states
from back.services.media.media_storage import is_archived
from back.services.videos.documents import read_transcript_documents, read_video_metadata
from back.services.videos.editing import mark_video_opened
from back.services.videos.list_state import card_list_states
from back.services.videos.playback import latest_playback_by_video, latest_playback_positions
from back.services.youtube.sponsor_segments import active_sponsor_segments, normalize_skip_segments
from back.services.youtube.subtitles import TranscriptLine, read_transcript_lines


class VideoNotFoundError(ValueError):
    def __init__(self) -> None:
        super().__init__("Vidéo introuvable")


@dataclass
class VideoDetail:
    video: Video
    # The user's own stars, comment, Vu/Indésirée and Nouveau on the fiche.
    state: UserVideo
    # `read_transcript_documents`: transcript, notes, summaries, questions, and the user's chat.
    documents: dict
    # The transcript line by line with the time each one starts, empty without a `.vtt` file.
    transcript_lines: list[TranscriptLine]
    # The fields of metadata.json the page shows, as yt-dlp wrote them.
    metadata: dict
    sponsor_segments: list[VideoSponsorSegment]
    sponsor_skip_enabled: bool
    # Sorted, merged and filtered segments the players skip (`normalize_skip_segments`).
    skip_segments: list[dict[str, float]]
    resume_positions: dict
    # The shared files were removed by the purge after the first Vu: none left, and nobody
    # rated the fiche high enough to keep them.
    files_purged: bool
    # The user's playlists, those the fiche can be added to.
    all_playlists: list[Playlist]
    category_label_styles: list[dict[str, str]]
    # How the fiche's card is greyed out for the user, and the state deduced from playback alone
    # (`card_list_states`): what the Vu and Indésirée buttons toggle from.
    shown_state: str
    auto_state: str


def read_timed_transcript(video: Video) -> list[TranscriptLine]:
    if not video.subtitle_path or not video.subtitle_path.lower().endswith(".vtt"):
        return []
    subtitle_file = local_media_path(video.subtitle_path)
    if not subtitle_file.is_file():
        return []
    try:
        return read_transcript_lines(subtitle_file)
    except Exception:
        # A broken file must not break the page: the transcript then shows as plain text.
        return []


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


def video_detail(db: Session, user_id: int, video: Video) -> VideoDetail:
    """Everything the page of a fiche shows the user, read only."""
    segments = active_sponsor_segments(db, video.id)
    state = video_states(db, user_id, [video.id])[video.id]
    shown_state, auto_state, _ = card_list_states(
        video,
        state,
        latest_playback_by_video(db, user_id, [video.id]).get(video.id),
        set(get_no_progress_category_labels(db)),
    )
    return VideoDetail(
        video=video,
        state=state,
        documents=read_transcript_documents(video, user_id),
        transcript_lines=read_timed_transcript(video),
        metadata=detail_metadata(read_video_metadata(video)),
        sponsor_segments=segments,
        sponsor_skip_enabled=get_sponsor_skip_enabled(db),
        skip_segments=normalize_skip_segments(segments),
        resume_positions=latest_playback_positions(db, user_id, video.id),
        files_purged=video.watched_at is not None
        and not video.video_path
        and not video.audio_path
        and not is_archived(db, video),
        all_playlists=list(
            db.scalars(select(Playlist).where(Playlist.user_id == user_id).order_by(Playlist.title))
        ),
        category_label_styles=get_video_category_label_styles(db),
        shown_state=shown_state,
        auto_state=auto_state,
    )


def open_video_detail(db: Session, user_id: int, video_id: int) -> VideoDetail:
    """The page of a fiche being opened: opening it takes the fiche out of the user's
    Nouveautés."""
    video = find_video(db, video_id)
    mark_video_opened(db, user_id, video)
    return video_detail(db, user_id, video)
