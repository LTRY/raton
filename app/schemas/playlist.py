from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.actions import JobQueuedRead


class PlaylistRead(BaseModel):
    id: int
    title: str
    source: str
    source_url: str | None
    yt_playlist_id: str | None
    categories: list[str]
    free_listening: bool
    created_at: datetime


class PlaylistSummaryRead(PlaylistRead):
    item_count: int
    # The first item's fiche, for the cover; None for an empty playlist.
    cover_video_id: int | None


class PlaylistItemRead(BaseModel):
    item_id: int
    position: int
    added_at: datetime | None
    video_id: int
    title: str
    channel_name: str | None
    duration_seconds: int
    has_audio: bool
    has_video: bool
    seen: bool


class PlaylistStatsRead(BaseModel):
    count: int
    total_duration_seconds: int
    seen_count: int
    missing_audio: int
    missing_video: int


class PlaylistDetailRead(PlaylistRead):
    stats: PlaylistStatsRead
    items: list[PlaylistItemRead]


class PlaylistCreate(BaseModel):
    title: str


class PlaylistTitleUpdate(BaseModel):
    title: str


class PlaylistCategoriesUpdate(BaseModel):
    categories: list[str]


class PlaylistCategoriesRead(BaseModel):
    playlist: PlaylistRead
    # Videos of the playlist without labels that received the playlist's.
    labelled_count: int


class PlaylistFreeListeningUpdate(BaseModel):
    enabled: bool


class PlaylistOrderUpdate(BaseModel):
    # Every item id of the playlist, in the new order.
    item_ids: list[int]


class PlaylistSortUpdate(BaseModel):
    # added, duration, title or reverse (`PLAYLIST_SORTS`).
    by: str


class PlaylistItemCreate(BaseModel):
    video_id: int


class PlaylistItemMove(BaseModel):
    direction: Literal["up", "down"]


class PlaylistPreviewRequest(BaseModel):
    url: str


class PlaylistPreviewRead(BaseModel):
    """What a playlist URL holds, read from YouTube without writing anything."""

    url: str
    title: str
    yt_playlist_id: str | None
    channel_name: str | None
    video_count: int
    unavailable_count: int
    duration_seconds: float
    unknown_duration_count: int
    known_in_library_count: int
    sample_titles: list[str]
    truncated: bool


class PlaylistUrlImport(BaseModel):
    url: str
    # Empty: the title YouTube gives the playlist.
    title: str = ""


class PlaylistImportRead(BaseModel):
    playlist: PlaylistRead
    job: JobQueuedRead


class PlaylistDownloadsRead(BaseModel):
    # One job per video without that format; empty when every video already has it.
    jobs: list[JobQueuedRead]
