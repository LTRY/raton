"""Vues enregistrees of the library: their stored form, parsed and normalized.

No DB access: `settings` reads and writes the stored list, this module only converts values.
"""

import json

from back.services.common.categories import parse_video_category_labels

# The file types a fiche can be filtered on (`video_asset_kind_condition`).
VIDEO_ASSET_KINDS = frozenset({"audio", "video", "metadata", "transcript", "imported", "shorts"})

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
        "assets": [asset for asset in assets if asset in VIDEO_ASSET_KINDS],
        "categories": categories,
        "excluded_assets": [asset for asset in excluded_assets if asset in VIDEO_ASSET_KINDS],
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
