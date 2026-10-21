"""Replies of `/api/scan`: the channel scan asked by hand, and its live event feed."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ScanStartedRead(BaseModel):
    # The last event before the scan's own: poll the feed from there.
    after: int


class ScanEventRead(BaseModel):
    id: int
    level: Literal["info", "error"]
    message: str
    # The last event of a scan: a viewer stops polling on it.
    final: bool


class ScanEventsRead(BaseModel):
    events: list[ScanEventRead]
    last_id: int
    running: bool


class ScanStatusRead(BaseModel):
    running: bool
    # The newest event of the feed: poll `/api/scan/events?after=` from there.
    last_event_id: int
    # The last scheduled scan (the 3am cron, or one asked by hand).
    last_at: datetime | None
    # completed, storage_low, rate_limited...; None before the first scan.
    last_status: str | None
    last_imported: int
