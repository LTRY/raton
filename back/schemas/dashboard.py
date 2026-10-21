"""Replies of `/api/nouveautes`, `/api/historique` and `/api/screen-time`."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from back.schemas.library import LibraryChannelRead, LibraryVideoRead
from back.schemas.video import Categories


class NouveautesStackRead(BaseModel):
    channel: LibraryChannelRead
    # The channel's most recent fiches of the kinds its bells follow, newest first.
    items: list[LibraryVideoRead]


class NouveautesRead(BaseModel):
    """`page` and `total_pages` count channels, ten per page."""

    stacks: list[NouveautesStackRead]
    page: int
    total_pages: int


class PlaybackRead(BaseModel):
    """One playback report, as a player sent it."""

    # "Lecture" from the start, "Reprise" further in.
    action: str
    # "vidéo" or "audio".
    media_label: str
    # Recorded at playback time: the only name left once the fiche is deleted.
    title: str
    position_seconds: float
    duration_seconds: float
    watched_seconds: float
    progress_percent: float
    is_completed: bool


class HistoryVideoRead(BaseModel):
    id: int
    title: str
    rating: int
    file_size_bytes: int
    list_state: str | None
    categories: Categories
    # What the fiche holds, in badge order: new, audio, video, metadata, transcript, notes,
    # imported.
    badges: list[str]


class HistoryRowRead(BaseModel):
    job_id: int
    created_at: datetime
    # The local day it sits under.
    day: date
    video: HistoryVideoRead | None
    channel: LibraryChannelRead | None
    playback: PlaybackRead
    shown_state: Literal["normal", "watched", "hidden"]
    auto_state: Literal["normal", "watched"]
    replay_category: bool


class HistoriqueRead(BaseModel):
    """The latest playback of each media, newest first, 50 per page."""

    rows: list[HistoryRowRead]
    page: int
    total_pages: int
    # Reading time of each day on the page, every playback of the day counted.
    day_seconds: dict[date, float]


class ScreenTimeItemRead(BaseModel):
    seconds: float
    # Distinct medias played.
    count: int
    # The day's limit for this kind, scaled to the period, in minutes.
    limit_minutes: int


class ScreenTimeRead(BaseModel):
    """Reading time per period (`today`, `week`, `month`) and kind (`video`, `short`,
    `podcast`, `music`)."""

    periods: dict[str, dict[str, ScreenTimeItemRead]]
