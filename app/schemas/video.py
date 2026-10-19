from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.models.video import TranscriptStatus


class VideoRead(BaseModel):
    id: int
    channel_id: int | None
    yt_video_id: str
    title: str
    url: str
    media_type: str
    published_at: datetime | None
    downloaded_at: datetime | None
    transcript_status: TranscriptStatus
    rating: int
    imported_via_form: bool
    category_labels: str | None
    file_size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class VideoPage(BaseModel):
    """One page of `GET /api/videos`; `total_pages` lets a client stop instead of looping."""

    items: list[VideoRead]
    page: int
    total_pages: int
    total: int


def optional_int(value) -> int | None:
    # metadata.json holds whatever yt-dlp wrote: a count can be missing or a non-numeric string.
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def optional_float(value) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


LenientInt = Annotated[int | None, BeforeValidator(optional_int)]
LenientFloat = Annotated[float | None, BeforeValidator(optional_float)]


class ChapterRead(BaseModel):
    title: str
    start_seconds: LenientFloat = None


class VideoMetadataRead(BaseModel):
    """The fields of metadata.json shown on the fiche."""

    description: str | None
    tags: list[str]
    chapters: list[ChapterRead]
    duration_seconds: LenientFloat
    view_count: LenientInt
    like_count: LenientInt
    comment_count: LenientInt
    uploader: str | None


class ChatMessageRead(BaseModel):
    role: str
    content: str


class VideoDocumentsRead(BaseModel):
    transcript: str | None
    notes: str | None
    short_summary: str | None
    suggested_questions: list[str]
    chat_messages: list[ChatMessageRead]


class SponsorSegmentRead(BaseModel):
    category: str
    start_seconds: float
    end_seconds: float

    model_config = ConfigDict(from_attributes=True)


class SkipSegmentRead(BaseModel):
    start: float
    end: float


class PlaybackPositionRead(BaseModel):
    position_seconds: float
    at_ms: int


class VideoPlaylistRead(BaseModel):
    playlist_id: int
    title: str
    item_id: int


class VideoMediaUrls(BaseModel):
    """Routes serving the fiche's files; None when the fiche has no such file."""

    video: str | None
    audio: str | None
    thumbnail: str | None
    subtitles: str | None


class VideoDetailRead(VideoRead):
    """`GET /api/videos/{id}`: what the page of a fiche shows, as raw values."""

    is_new: bool
    list_state: str | None
    comment: str | None
    duration_seconds: int | None
    watched_at: datetime | None
    media_urls: VideoMediaUrls
    metadata: VideoMetadataRead
    documents: VideoDocumentsRead
    sponsor_segments: list[SponsorSegmentRead]
    sponsor_skip_enabled: bool
    skip_segments: list[SkipSegmentRead]
    resume_positions: dict[str, PlaybackPositionRead]
    playlists: list[VideoPlaylistRead]
