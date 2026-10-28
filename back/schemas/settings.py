from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from back.services.common.curfew import normalize_curfew_time


class CategoryStyleRead(BaseModel):
    label: str
    # `#rrggbb`.
    color: str


class SponsorCategoryRead(BaseModel):
    value: str
    label: str


class CurfewRead(BaseModel):
    """The couvre-feu: `HH:MM` hours in Europe/Paris, from `start` to `end`, possibly across
    midnight."""

    enabled: bool
    start: str
    end: str
    # Enabled, now in the range and not skipped for tonight: the API only answers the routes it
    # leaves open.
    active: bool
    ends_at: datetime | None
    # End of the "pas ce soir" skip in force, `null` when none is.
    skipped_until: datetime | None


class RatonLanguageRead(BaseModel):
    """How Raton speaks to the user in the chat."""

    # "vous" or "tu".
    address: str
    # The name Raton calls the user by; empty for none.
    nickname: str


class SettingsRead(BaseModel):
    media_root: str
    global_quota_bytes: int
    video_category_labels: list[str]
    video_category_label_styles: list[dict[str, str]]
    video_library_views: list[dict]
    # Categories whose fiches are replayed, never "done": no progress bar, no automatic Vu.
    no_progress_category_labels: list[str]
    auto_notes_enabled: bool
    auto_notes_excluded_category_labels: list[str]
    # SponsorBlock categories searched, and whether the players skip their segments.
    sponsor_segment_categories: list[str]
    sponsor_skip_enabled: bool
    # Every SponsorBlock category Raton knows, with its French name.
    sponsor_segment_category_choices: list[SponsorCategoryRead]
    # Minutes allowed per kind (`video`, `short`, `podcast`, `music`) and period (`today`,
    # `week`, `month`; the week and month ones are the day's, scaled).
    screen_time_limits: dict[str, dict[str, int]]
    curfew: CurfewRead
    raton_language: RatonLanguageRead
    # Who answers the LLM requests, such as "Claude API (claude-haiku-4-5)"; set by the
    # environment, so not in `SettingsUpdate`.
    llm_provider_label: str


class ScreenTimeMinutesUpdate(BaseModel):
    """Minutes allowed per day; a missing kind keeps its limit, every limit is at least 1."""

    video: int | None = None
    short: int | None = None
    podcast: int | None = None
    music: int | None = None


class SettingsUpdate(BaseModel):
    """Only the given fields change; lists replace the stored ones, normalized."""

    media_root: str | None = None
    global_quota_bytes: int | None = None
    video_category_labels: list[str] | None = None
    video_category_label_styles: list[dict[str, str]] | None = None
    video_library_views: list[dict] | None = None
    no_progress_category_labels: list[str] | None = None
    auto_notes_enabled: bool | None = None
    auto_notes_excluded_category_labels: list[str] | None = None
    sponsor_segment_categories: list[str] | None = None
    sponsor_skip_enabled: bool | None = None
    screen_time_today_minutes: ScreenTimeMinutesUpdate | None = None
    curfew_enabled: bool | None = None
    curfew_start: str | None = None
    curfew_end: str | None = None
    raton_address: Literal["vous", "tu"] | None = None
    raton_nickname: str | None = None

    @field_validator("curfew_start", "curfew_end")
    @classmethod
    def curfew_time(cls, value: str | None) -> str | None:
        return None if value is None else normalize_curfew_time(value)
