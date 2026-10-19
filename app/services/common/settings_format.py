"""Stored form of the category labels and library views settings: parse, normalize, serialize.

No database access: `settings` reads and writes the rows, this module only converts their values.
"""

import json

DEFAULT_VIDEO_CATEGORY_LABELS = [
    "cuisine",
    "maker",
    "science",
    "entertainment",
    "podcasts",
    "economie",
]
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
DEFAULT_VIDEO_CATEGORY_COLORS = ["#16a34a", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0891b2"]


def normalize_video_category_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def serialized_category_labels(labels: list[str]) -> str | None:
    """Labels as stored on a channel, fiche or playlist: normalized, deduplicated, comma-joined."""
    normalized = []
    for label in labels:
        normalized_label = normalize_video_category_label(label)
        if normalized_label and normalized_label not in normalized:
            normalized.append(normalized_label)
    return ",".join(normalized) or None


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
