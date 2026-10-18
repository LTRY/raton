from pydantic import BaseModel


class SettingsRead(BaseModel):
    media_root: str
    global_quota_bytes: int
    video_category_labels: list[str]
    video_category_label_styles: list[dict[str, str]]
    video_library_views: list[dict]


class SettingsUpdate(BaseModel):
    media_root: str | None = None
    global_quota_bytes: int | None = None
    video_category_labels: list[str] | None = None
    video_category_label_styles: list[dict[str, str]] | None = None
    video_library_views: list[dict] | None = None
