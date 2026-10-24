from datetime import datetime
from typing import Annotated

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field

from back.models.video import TranscriptStatus
from back.services.common.categories import parse_video_category_labels


def category_list(value) -> list[str]:
    # The column stores "label,label"; a list is one already (a model built from another model).
    if isinstance(value, list):
        return value
    return parse_video_category_labels(value)


# `categories` read from the `category_labels` column of a channel or a fiche.
Categories = Annotated[
    list[str],
    BeforeValidator(category_list),
    Field(validation_alias=AliasChoices("categories", "category_labels")),
]


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
    # The reading user's own stars (`user_videos`), not a column of the fiche.
    rating: int
    imported_via_form: bool
    categories: Categories
    file_size_bytes: int

    @classmethod
    def of(cls, video, rating: int) -> VideoRead:
        """A fiche as one user sees it: its columns, plus that user's `rating`."""
        own = {"rating", "categories"}
        fields = {name: getattr(video, name) for name in VideoRead.model_fields if name not in own}
        return cls(**fields, rating=rating, categories=video.category_labels)


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

    @classmethod
    def from_documents(cls, documents: dict) -> VideoDocumentsRead:
        """From `read_transcript_documents`."""
        return cls(
            transcript=documents["transcript"],
            notes=documents["notes_transcript"],
            short_summary=documents["short_summary"],
            suggested_questions=documents["suggested_questions"],
            chat_messages=documents["chat_messages"],
        )


class SponsorSegmentRead(BaseModel):
    category: str
    start_seconds: float
    end_seconds: float

    model_config = ConfigDict(from_attributes=True)


class TranscriptLineRead(BaseModel):
    start_seconds: float
    text: str

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


class VideoChannelRead(BaseModel):
    id: int
    name: str


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
    # The purge removed the shared files after the first Vu (anyone's): the page says so.
    files_purged: bool
    # The user's playlists that hold the fiche.
    playlists: list[VideoPlaylistRead]
    channel: VideoChannelRead | None
    # What the fiche holds, in badge order: new, audio, video, metadata, transcript, notes,
    # imported (manual import).
    badges: list[str]
    # A transcript is recorded (its file may still be missing: `documents.transcript` is null).
    has_transcript: bool
    # The transcript line by line with the time each one starts (from the `.vtt` subtitles),
    # empty without them.
    transcript_lines: list[TranscriptLineRead]
