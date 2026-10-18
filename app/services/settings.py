import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import log_event
from app.models.setting import AppSetting

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
DEFAULT_VIDEO_CATEGORY_LABELS = [
    "cuisine",
    "maker",
    "science",
    "entertainment",
    "podcasts",
    "economie",
]
DEFAULT_NO_PROGRESS_CATEGORY_LABELS = ["amv", "musique"]
# Content whose structured notes would add noise to the cross-video search (recipes, clips, ...).
DEFAULT_AUTO_NOTES_EXCLUDED_CATEGORY_LABELS = [
    "cuisine",
    "amv",
    "musique",
    "sport",
    "entertainment",
]
DEFAULT_VIDEO_CATEGORY_COLORS = ["#16a34a", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0891b2"]
DEFAULT_VIDEO_LIBRARY_VIEWS = [
    {
        "name": "Notés",
        "asset_filter_mode": "or",
        "category_filter_mode": "or",
        "assets": [],
        "categories": [],
        "excluded_assets": [],
        "excluded_categories": [],
        "rated": True,
    }
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


def normalize_video_category_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def parse_video_category_labels(value: str | None) -> list[str]:
    if not value:
        return []
    labels = []
    for item in value.replace("\n", ",").split(","):
        label = normalize_video_category_label(item)
        if label and label not in labels:
            labels.append(label)
    return labels


def normalize_video_category_color(color: str | None, fallback: str = "#16a34a") -> str:
    if not isinstance(color, str):
        return fallback
    color = color.strip()
    if len(color) != 7 or not color.startswith("#"):
        return fallback
    if not all(char in "0123456789abcdefABCDEF" for char in color[1:]):
        return fallback
    return color.lower()


def video_category_text_color(color: str) -> str:
    color = normalize_video_category_color(color)
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    return "#0f172a" if brightness > 150 else "#ffffff"


def video_category_css_style(label_style: dict[str, str]) -> str:
    color = normalize_video_category_color(label_style.get("color"))
    return f"--category-bg: {color}; --category-border: {color}; --category-text: {video_category_text_color(color)};"


def serialize_video_category_label_styles(label_styles: list[dict[str, str]]) -> str:
    styles = []
    for index, item in enumerate(label_styles):
        label = normalize_video_category_label(item.get("label", ""))
        if not label or any(existing["label"] == label for existing in styles):
            continue
        fallback = DEFAULT_VIDEO_CATEGORY_COLORS[index % len(DEFAULT_VIDEO_CATEGORY_COLORS)]
        styles.append(
            {"label": label, "color": normalize_video_category_color(item.get("color"), fallback)}
        )
    return json.dumps(styles, ensure_ascii=False, separators=(",", ":"))


def parse_video_category_label_styles(value: str | None) -> list[dict[str, str]]:
    if not value:
        return [
            {
                "label": label,
                "color": DEFAULT_VIDEO_CATEGORY_COLORS[index % len(DEFAULT_VIDEO_CATEGORY_COLORS)],
            }
            for index, label in enumerate(DEFAULT_VIDEO_CATEGORY_LABELS)
        ]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        styles = []
        for index, item in enumerate(parsed):
            if isinstance(item, dict):
                label = normalize_video_category_label(str(item.get("label", "")))
                color = item.get("color")
            else:
                label = normalize_video_category_label(str(item))
                color = None
            if not label or any(existing["label"] == label for existing in styles):
                continue
            fallback = DEFAULT_VIDEO_CATEGORY_COLORS[index % len(DEFAULT_VIDEO_CATEGORY_COLORS)]
            styles.append(
                {"label": label, "color": normalize_video_category_color(color, fallback)}
            )
        if styles:
            return styles
    legacy_labels = parse_video_category_labels(value)
    return [
        {
            "label": label,
            "color": DEFAULT_VIDEO_CATEGORY_COLORS[index % len(DEFAULT_VIDEO_CATEGORY_COLORS)],
        }
        for index, label in enumerate(legacy_labels or DEFAULT_VIDEO_CATEGORY_LABELS)
    ]


def normalize_video_filter_mode(value: str | None) -> str:
    return value if value in {"and", "or"} else "or"


def normalize_video_library_view(item: dict | None) -> dict[str, str | bool | list[str]]:
    if not isinstance(item, dict):
        item = {}
    name = " ".join(str(item.get("name") or "").strip().split())
    asset_values = item.get("assets", [])
    if not isinstance(asset_values, list):
        asset_values = []
    assets = parse_video_category_labels(",".join(str(asset) for asset in asset_values))
    valid_assets = {"audio", "video", "metadata", "transcript", "imported", "shorts"}
    excluded_asset_values = item.get("excluded_assets", [])
    if not isinstance(excluded_asset_values, list):
        excluded_asset_values = []
    excluded_assets = parse_video_category_labels(
        ",".join(str(asset) for asset in excluded_asset_values)
    )
    category_values = item.get("categories", [])
    if not isinstance(category_values, list):
        category_values = []
    categories = parse_video_category_labels(
        ",".join(str(category) for category in category_values)
    )
    excluded_category_values = item.get("excluded_categories", [])
    if not isinstance(excluded_category_values, list):
        excluded_category_values = []
    excluded_categories = parse_video_category_labels(
        ",".join(str(category) for category in excluded_category_values)
    )
    return {
        "name": name,
        "asset_filter_mode": normalize_video_filter_mode(str(item.get("asset_filter_mode") or "")),
        "category_filter_mode": normalize_video_filter_mode(
            str(item.get("category_filter_mode") or "")
        ),
        "assets": [asset for asset in assets if asset in valid_assets],
        "categories": categories,
        "excluded_assets": [asset for asset in excluded_assets if asset in valid_assets],
        "excluded_categories": excluded_categories,
        "rated": bool(item.get("rated")),
    }


def serialize_video_library_views(views: list[dict]) -> str:
    normalized = []
    seen_names = set()
    for item in views:
        view = normalize_video_library_view(item)
        name = str(view["name"])
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        normalized.append(view)
    return json.dumps(
        normalized or DEFAULT_VIDEO_LIBRARY_VIEWS, ensure_ascii=False, separators=(",", ":")
    )


def parse_video_library_views(value: str | None) -> list[dict[str, str | bool | list[str]]]:
    if not value:
        return DEFAULT_VIDEO_LIBRARY_VIEWS
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, list):
        return DEFAULT_VIDEO_LIBRARY_VIEWS
    normalized = json.loads(serialize_video_library_views(parsed))
    return normalized or DEFAULT_VIDEO_LIBRARY_VIEWS


def serialize_video_category_labels(labels: list[str]) -> str:
    return ",".join(parse_video_category_labels(",".join(labels)))


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
