from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.actions import JobQueuedRead


class ChannelCreate(BaseModel):
    url: str
    rating: int = Field(default=1, ge=0, le=5)


class ChannelRead(BaseModel):
    id: int
    url: str
    name: str
    yt_channel_id: str | None
    rating: int
    category_labels: str | None

    model_config = ConfigDict(from_attributes=True)


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
