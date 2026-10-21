from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.actions import JobQueuedRead
from app.schemas.video import Categories


class ChannelCreate(BaseModel):
    url: str
    # Checked by the service (`check_rating`), whose refusal is the French message.
    rating: int = 1


class RatingUpdate(BaseModel):
    rating: int


class ChannelRead(BaseModel):
    id: int
    url: str
    name: str
    yt_channel_id: str | None
    rating: int
    categories: Categories
    auto_metadata_enabled: bool
    auto_shorts_enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelListItemRead(ChannelRead):
    video_count: int
    # Last playback of one of its fiches; None if none was ever played.
    last_played_at: datetime | None


class ChannelPageRead(BaseModel):
    """`GET /api/channels`: one page of the channels, in the order and filter asked."""

    items: list[ChannelListItemRead]
    sort: str
    page: int
    total_pages: int
    total: int


class ChannelDetailRead(ChannelRead):
    description: str | None
    keywords: list[str]
    # Routes serving the profile images; None when the channel has none.
    avatar_url: str | None
    banner_url: str | None
    metadata_fetched_at: datetime | None
    last_scanned_at: datetime | None
    video_count: int


BellSection = Literal["videos", "shorts"]


class ChannelStateRead(BaseModel):
    """The editable fields of a channel, as stored after an action."""

    id: int
    name: str
    rating: int
    categories: list[str]
    auto_metadata_enabled: bool
    auto_shorts_enabled: bool


class ChannelCategoriesUpdate(BaseModel):
    categories: list[str]


class ChannelBellUpdate(BaseModel):
    enabled: bool


class ChannelBellRead(BaseModel):
    channel: ChannelStateRead
    # The catalogue sync queued when the cloche has just been turned on, else None.
    job: JobQueuedRead | None


class ChannelMetadataImport(BaseModel):
    page: int = Field(default=1, ge=1)
    section: BellSection = "videos"


class ChannelProfileRefreshRead(BaseModel):
    status: str
    message: str


class SubscriptionRowRead(BaseModel):
    channel_id: str
    url: str
    name: str
    already_imported: bool
    # What `POST /api/channels/import-csv/confirm` takes back; None for a channel already in.
    token: str | None


class SubscriptionsPreviewRead(BaseModel):
    rows: list[SubscriptionRowRead]
    new_count: int
    existing_count: int


class SubscriptionsConfirm(BaseModel):
    tokens: list[str]


class SubscriptionsAddedRead(BaseModel):
    added: int
