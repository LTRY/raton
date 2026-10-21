from pydantic import BaseModel


class CategoryStyleRead(BaseModel):
    label: str
    # `#rrggbb`.
    color: str


class SponsorCategoryRead(BaseModel):
    value: str
    label: str


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
