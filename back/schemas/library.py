from typing import Literal

from pydantic import BaseModel

from back.schemas.video import VideoRead


class CardPlaybackRead(BaseModel):
    """Last playback of a fiche: what its progress bar shows."""

    position_seconds: float
    duration_seconds: float
    progress_percent: float
    is_completed: bool


class LibraryVideoRead(VideoRead):
    channel_name: str | None
    duration_seconds: int | None
    view_count: int | None
    is_new: bool
    list_state: str | None
    has_video: bool
    has_audio: bool
    has_thumbnail: bool
    playback: CardPlaybackRead | None
    # How the card is greyed out: `list_state` when set, else deduced from the playback.
    shown_state: Literal["normal", "watched", "hidden"]
    # The state deduced from the playback alone: what "clear" brings back.
    auto_state: Literal["normal", "watched"]
    # In a "no progress bar" category (Paramètres): never a progress bar, never Vu by playback.
    replay_category: bool


class LibraryChannelRead(BaseModel):
    id: int
    name: str


class LibraryFiltersRead(BaseModel):
    """The filters actually applied, after defaults and normalization."""

    channel_id: int | None
    sort: str
    assets: list[str]
    categories: list[str]
    excluded_assets: list[str]
    excluded_categories: list[str]
    rated: bool
    # "none" or "watched_hidden": what the list leaves out (the Vu and Indésirée fiches).
    hide: str
    uncategorized: bool
    asset_filter_mode: str
    category_filter_mode: str
    q: str


class SavedViewRead(BaseModel):
    name: str
    active: bool
    assets: list[str]
    categories: list[str]
    excluded_assets: list[str]
    excluded_categories: list[str]
    rated: bool
    asset_filter_mode: str
    category_filter_mode: str


class LibraryPageRead(BaseModel):
    """`GET /api/library`: what the library list (or a channel page) shows for these filters."""

    filters: LibraryFiltersRead
    channel: LibraryChannelRead | None
    section: str
    page: int
    total_pages: int
    total: int
    counts: dict[str, int]
    items: list[LibraryVideoRead]
    saved_views: list[SavedViewRead]
    # A channel page only (null otherwise): median days between two publications, and the
    # page of the channel's YouTube listing "Explorer la suite" imports next.
    publication_interval_days: float | None
    explore_next_page: int | None
    # Fiches one exploration imports.
    explore_page_size: int
