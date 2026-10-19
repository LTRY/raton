import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import log_event
from app.models.setting import AppSetting
from app.services.common.settings_format import (
    DEFAULT_VIDEO_CATEGORY_COLORS,
    DEFAULT_VIDEO_CATEGORY_LABELS,
    DEFAULT_VIDEO_LIBRARY_VIEWS,
    parse_video_category_label_styles,
    parse_video_category_labels,
    parse_video_library_views,
    serialize_video_category_label_styles,
    serialize_video_library_views,
)

logger = logging.getLogger(__name__)
MEDIA_ROOT_KEY = "media_root"
GLOBAL_QUOTA_BYTES_KEY = "global_quota_bytes"
VIDEO_CATEGORY_LABELS_KEY = "video_category_labels"
NO_PROGRESS_CATEGORY_LABELS_KEY = "no_progress_category_labels"
AUTO_NOTES_ENABLED_KEY = "auto_notes_enabled"
AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY = "auto_notes_excluded_category_labels"
SPONSOR_SEGMENT_CATEGORIES_KEY = "sponsor_segment_categories"
SPONSOR_SEGMENT_CATEGORY_CHOICES = ["sponsor", "selfpromo", "interaction", "intro", "outro"]
SPONSOR_SEGMENT_CATEGORY_LABELS = {
    "sponsor": "Sponsor",
    "selfpromo": "Auto-promotion",
    "interaction": "Rappel abonnement/like",
    "intro": "Intro",
    "outro": "Outro",
}
SPONSOR_SKIP_ENABLED_KEY = "sponsor_skip_enabled"
VIDEO_LIBRARY_VIEWS_KEY = "video_library_views"
SCREEN_TIME_KINDS = ("video", "short", "podcast", "music")
SCREEN_TIME_PERIOD_MULTIPLIERS = {"today": 1, "week": 7, "month": 30}
SCREEN_TIME_LIMIT_KEYS = {
    kind: f"screen_time_{kind}_today_limit_minutes" for kind in SCREEN_TIME_KINDS
}
DEFAULT_SCREEN_TIME_LIMITS = {
    "video": 120,
    "short": 30,
    "podcast": 120,
    "music": 180,
}
DEFAULT_NO_PROGRESS_CATEGORY_LABELS = ["amv", "musique"]
# Content whose structured notes would add noise to the cross-video search (recipes, clips, ...).
DEFAULT_AUTO_NOTES_EXCLUDED_CATEGORY_LABELS = [
    "cuisine",
    "amv",
    "musique",
    "sport",
    "entertainment",
]


def get_setting(db: Session, key: str, default: str) -> str:
    setting = db.get(AppSetting, key)
    return setting.value if setting else default


def set_setting(db: Session, key: str, value: str) -> AppSetting:
    setting = db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    # The key only: values can be secrets or long prompts.
    log_event(logger, "setting.set", key=key)
    return setting


def get_media_root(db: Session) -> Path:
    return Path(get_setting(db, MEDIA_ROOT_KEY, str(get_settings().media_root))).expanduser()


def get_global_quota_bytes(db: Session) -> int:
    return int(get_setting(db, GLOBAL_QUOTA_BYTES_KEY, str(get_settings().global_quota_bytes)))


def get_llm_provider_name() -> str:
    return get_settings().llm_provider.strip().lower()


def get_llm_provider_display_label() -> str:
    """Short human-readable name of the AI currently doing the work, for status messages."""
    provider = get_llm_provider_name()
    settings = get_settings()
    if provider == "anthropic":
        return f"Claude API ({settings.anthropic_model})"
    return provider


def default_video_category_labels_value() -> str:
    return serialize_video_category_label_styles(
        [
            {
                "label": label,
                "color": DEFAULT_VIDEO_CATEGORY_COLORS[index % len(DEFAULT_VIDEO_CATEGORY_COLORS)],
            }
            for index, label in enumerate(DEFAULT_VIDEO_CATEGORY_LABELS)
        ]
    )


def get_video_category_labels(db: Session) -> list[str]:
    return [item["label"] for item in get_video_category_label_styles(db)]


def get_video_category_label_styles(db: Session) -> list[dict[str, str]]:
    return parse_video_category_label_styles(
        get_setting(db, VIDEO_CATEGORY_LABELS_KEY, default_video_category_labels_value())
    )


def default_no_progress_category_labels_value() -> str:
    return ",".join(DEFAULT_NO_PROGRESS_CATEGORY_LABELS)


def get_no_progress_category_labels(db: Session) -> list[str]:
    return parse_video_category_labels(
        get_setting(
            db, NO_PROGRESS_CATEGORY_LABELS_KEY, default_no_progress_category_labels_value()
        )
    )


def default_auto_notes_excluded_category_labels_value() -> str:
    return ",".join(DEFAULT_AUTO_NOTES_EXCLUDED_CATEGORY_LABELS)


def get_auto_notes_excluded_category_labels(db: Session) -> list[str]:
    return parse_video_category_labels(
        get_setting(
            db,
            AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY,
            default_auto_notes_excluded_category_labels_value(),
        )
    )


def get_auto_notes_enabled(db: Session) -> bool:
    return get_setting(db, AUTO_NOTES_ENABLED_KEY, "true") == "true"


def default_sponsor_segment_categories_value() -> str:
    return ",".join(SPONSOR_SEGMENT_CATEGORY_CHOICES)


def get_sponsor_segment_categories(db: Session) -> list[str]:
    value = get_setting(
        db, SPONSOR_SEGMENT_CATEGORIES_KEY, default_sponsor_segment_categories_value()
    )
    selected = {item.strip() for item in value.split(",") if item.strip()}
    return [category for category in SPONSOR_SEGMENT_CATEGORY_CHOICES if category in selected]


def get_sponsor_skip_enabled(db: Session) -> bool:
    return get_setting(db, SPONSOR_SKIP_ENABLED_KEY, "true") == "true"


def default_video_library_views_value() -> str:
    return serialize_video_library_views(DEFAULT_VIDEO_LIBRARY_VIEWS)


def get_video_library_views(db: Session) -> list[dict[str, str | bool | list[str]]]:
    return parse_video_library_views(
        get_setting(db, VIDEO_LIBRARY_VIEWS_KEY, default_video_library_views_value())
    )


def get_screen_time_limits(db: Session) -> dict[str, dict[str, int]]:
    return {
        kind: {
            period: max(
                1, int(get_setting(db, SCREEN_TIME_LIMIT_KEYS[kind], str(default))) * multiplier
            )
            for period, multiplier in SCREEN_TIME_PERIOD_MULTIPLIERS.items()
        }
        for kind, default in DEFAULT_SCREEN_TIME_LIMITS.items()
    }


def add_video_category_labels(db: Session, labels: list[str]) -> list[dict[str, str]]:
    styles = get_video_category_label_styles(db)
    existing_labels = {style["label"] for style in styles}
    for label in parse_video_category_labels(",".join(labels)):
        if label in existing_labels:
            continue
        color = DEFAULT_VIDEO_CATEGORY_COLORS[len(styles) % len(DEFAULT_VIDEO_CATEGORY_COLORS)]
        styles.append({"label": label, "color": color})
        existing_labels.add(label)
    set_setting(db, VIDEO_CATEGORY_LABELS_KEY, serialize_video_category_label_styles(styles))
    return styles


def ensure_default_settings(db: Session) -> None:
    settings = get_settings()
    defaults = {
        MEDIA_ROOT_KEY: str(settings.media_root),
        GLOBAL_QUOTA_BYTES_KEY: str(settings.global_quota_bytes),
        VIDEO_CATEGORY_LABELS_KEY: default_video_category_labels_value(),
        NO_PROGRESS_CATEGORY_LABELS_KEY: default_no_progress_category_labels_value(),
        AUTO_NOTES_ENABLED_KEY: "true",
        AUTO_NOTES_EXCLUDED_CATEGORY_LABELS_KEY: default_auto_notes_excluded_category_labels_value(),
        SPONSOR_SEGMENT_CATEGORIES_KEY: default_sponsor_segment_categories_value(),
        SPONSOR_SKIP_ENABLED_KEY: "true",
        VIDEO_LIBRARY_VIEWS_KEY: default_video_library_views_value(),
        **{
            SCREEN_TIME_LIMIT_KEYS[kind]: str(value)
            for kind, value in DEFAULT_SCREEN_TIME_LIMITS.items()
        },
    }
    for key, value in defaults.items():
        if db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value=value))
    db.commit()
