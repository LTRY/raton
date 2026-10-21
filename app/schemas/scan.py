"""Replies of `/api/scan`: the channel scan asked by hand, and its live event feed."""

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
