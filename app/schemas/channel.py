from pydantic import BaseModel, ConfigDict, Field


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
