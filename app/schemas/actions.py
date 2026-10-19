"""Bodies and replies of the `/api` actions on a fiche and of `GET /api/jobs/{id}`."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.video import SkipSegmentRead


class ListStateUpdate(BaseModel):
    # watched, unwatched, hidden, or clear to go back to the state deduced from playback.
    state: str


class CategoriesUpdate(BaseModel):
    categories: list[str]


class CommentUpdate(BaseModel):
    comment: str


class PlaybackActivity(BaseModel):
    media_type: str = "video"
    position_seconds: float = 0
    duration_seconds: float = 0
    watched_seconds: float = 0


class MediaDownload(BaseModel):
    video_quality: str = "1080"


class VideoStateRead(BaseModel):
    """The editable fields of a fiche, as stored after an action."""

    id: int
    is_new: bool
    list_state: str | None
    rating: int
    categories: list[str]
    comment: str | None
    watched_at: datetime | None


class JobQueuedRead(BaseModel):
    job_id: int
    status: str
    message: str
    status_url: str


class JobStatusRead(BaseModel):
    id: int
    status: str
    message: str
    video_id: int | None
    done: bool
    # Only for a channel exploration: the fiches imported so far.
    videos: list[dict] | None = None


class SponsorSegmentsFetchRead(BaseModel):
    count: int
    skip_enabled: bool
    segments: list[SkipSegmentRead]
