from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
