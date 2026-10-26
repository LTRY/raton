"""The library list of `/videos` (Exploration, a channel's page) and of the Nouveautés: from the
URL to `GET /api/library`, and back to the links of the page (filter pills, saved views, "Tout
effacer")."""

from urllib.parse import urlencode

from fastapi import Request

from front.api import Api
from front.cards import card_views
from front.formatting import category_style_map, format_periodicity_rate
from front.pages import current_request_path, list_hide_selector, page_href_builder
from front.records import record

# Shorts mosaic: a big tile every SHORTS_FEATURE_RHYTHM tiles, never closer than SHORTS_FEATURE_MIN_GAP positions
# (a big tile is 2x2, so two of them next to each other would swallow the mosaic).
SHORTS_FEATURE_RHYTHM = 7
SHORTS_FEATURE_MIN_GAP = 6

DEFAULT_VIDEO_ASSET_FILTERS = {"audio", "video"}

VIDEO_ASSET_FILTER_OPTIONS = [
    {"text": "Vidéo", "kind": "video"},
    {"text": "Shorts", "kind": "shorts"},
    {"text": "Métadonnées", "kind": "metadata"},
    {"text": "Transcript", "kind": "transcript"},
    {"text": "Audio", "kind": "audio"},
    {"text": "Manuelles", "kind": "imported"},
]

DEFAULT_CHANNEL_VIDEO_ASSET_FILTERS = {option["kind"] for option in VIDEO_ASSET_FILTER_OPTIONS}


def normalized_channel_id(channel_id: int | str | None) -> int | None:
    if channel_id in (None, ""):
        return None
    return int(channel_id)


def selected_video_asset_filters(
    request: Request, channel_id: int | None, followed: bool = False
) -> list[str]:
    """The file types the URL asks for; until the form is submitted, the page's preset ones
    (every type on a channel page and in the Nouveautés, whose fiches are mostly metadata only)."""
    if request.query_params.get("asset_filters") != "1":
        if channel_id or followed:
            return sorted(DEFAULT_CHANNEL_VIDEO_ASSET_FILTERS)
        return sorted(DEFAULT_VIDEO_ASSET_FILTERS)
    return request.query_params.getlist("asset")


def selected_video_filter_mode(request: Request, name: str) -> str:
    mode = request.query_params.get(name)
    if mode in {"and", "or", "not"}:
        return mode
    mode = request.query_params.get("filter_mode")
    if mode in {"and", "or", "not"}:
        return mode
    if name == "asset_filter_mode" and request.query_params.get("rated") == "1":
        return "and"
    return "or"


def library_query(
    request: Request, channel_id: int | None, page: int, followed: bool = False
) -> dict:
    """The `GET /api/library` parameters of this page's URL."""
    params = request.query_params
    query = {
        "channel_id": channel_id,
        "section": params.get("section"),
        "sort": params.get("sort"),
        "asset": selected_video_asset_filters(request, channel_id, followed),
        "category": params.getlist("category"),
        "exclude_asset": params.getlist("exclude_asset"),
        "exclude_category": params.getlist("exclude_category"),
        "asset_filter_mode": selected_video_filter_mode(request, "asset_filter_mode"),
        "category_filter_mode": selected_video_filter_mode(request, "category_filter_mode"),
        "q": params.get("q"),
        "hide": params.get("hide"),
        "page": max(page, 1),
    }
    if followed:
        query["followed"] = "true"
    for flag, name in (
        ("rated", "rated"),
        ("uncategorized", "uncategorized"),
    ):
        if params.get(flag) == "1":
            query[name] = "true"
    return query


def query_without(request: Request, remove: list[tuple[str, str | None]]) -> str:
    def matches(key: str, value: str) -> bool:
        return any(rk == key and (rv is None or rv == value) for rk, rv in remove)

    pairs = [
        (key, value) for key, value in request.query_params.multi_items() if not matches(key, value)
    ]
    query = urlencode(pairs)
    return f"{request.url.path}?{query}" if query else request.url.path


def video_filters_clear_href(request: Request) -> str:
    # `hide` is how the list is shown, not a filter: "Tout effacer" keeps it.
    keep_keys = {"channel_id", "section", "sort", "q", "hide"}
    pairs = [(key, value) for key, value in request.query_params.multi_items() if key in keep_keys]
    pairs.append(("asset_filters", "1"))
    return f"{request.url.path}?{urlencode(pairs)}"


def video_active_filter_pills(request: Request, filters) -> list[dict]:
    pills = []
    assets = set(filters.assets)
    # A channel page and the Nouveautés select every file type by default: that is "no filter",
    # so they show no pill.
    if (filters.channel_id or filters.followed) and assets == DEFAULT_CHANNEL_VIDEO_ASSET_FILTERS:
        assets = set()
    if filters.rated:
        pills.append(
            {
                "label": "★ Notées",
                "kind": "include",
                "href": query_without(request, [("rated", None)]),
            }
        )
    for option in VIDEO_ASSET_FILTER_OPTIONS:
        kind = option["kind"]
        if kind in assets:
            pills.append(
                {
                    "label": option["text"],
                    "kind": "include",
                    "href": query_without(request, [("asset", kind)]),
                }
            )
        if kind in filters.excluded_assets:
            pills.append(
                {
                    "label": option["text"],
                    "kind": "exclude",
                    "href": query_without(request, [("exclude_asset", kind)]),
                }
            )
    if filters.uncategorized:
        pills.append(
            {
                "label": "Sans catégorie",
                "kind": "include",
                "href": query_without(request, [("uncategorized", None)]),
            }
        )
    for category in sorted(filters.categories):
        pills.append(
            {
                "label": category,
                "kind": "include",
                "href": query_without(request, [("category", category)]),
            }
        )
    for category in sorted(filters.excluded_categories):
        pills.append(
            {
                "label": category,
                "kind": "exclude",
                "href": query_without(request, [("exclude_category", category)]),
            }
        )
    return pills


def video_library_view_path(view, request: Request) -> str:
    params: list[tuple[str, str]] = [("asset_filters", "1")]
    for name in ("channel_id", "section", "sort"):
        value = request.query_params.get(name)
        if value:
            params.append((name, value))
    params.append(("asset_filter_mode", str(view.asset_filter_mode or "or")))
    params.append(("category_filter_mode", str(view.category_filter_mode or "or")))
    for asset in view.assets:
        params.append(("asset", str(asset)))
    for asset in view.excluded_assets:
        params.append(("exclude_asset", str(asset)))
    for category in view.categories:
        params.append(("category", str(category)))
    for category in view.excluded_categories:
        params.append(("exclude_category", str(category)))
    if view.rated:
        params.append(("rated", "1"))
    return f"/videos?{urlencode(params)}"


def library_view_links(views, request: Request) -> list[dict]:
    """The vues enregistrees as links of the Bibliothèque menu."""
    return [
        {"name": view.name, "active": view.active, "href": video_library_view_path(view, request)}
        for view in views
    ]


def library_list_context(request: Request, api: Api, library) -> dict:
    """What `videos.html` (and `channel_videos.html`) read of a `GET /api/library` reply."""
    filters = library.filters
    styles = record(api.get("/categories"))
    cards = card_views(library.items)
    return {
        "channels": record(api.get("/channels/names")),
        "selected_channel_id": filters.channel_id,
        "selected_channel_section": library.section,
        "asset_filter_options": VIDEO_ASSET_FILTER_OPTIONS,
        "selected_asset_filters": set(filters.assets),
        "category_filter_options": styles,
        "category_style_map": category_style_map(styles),
        "library_views": library_view_links(library.saved_views, request),
        "selected_category_filters": set(filters.categories),
        "selected_excluded_asset_filters": set(filters.excluded_assets),
        "selected_excluded_category_filters": set(filters.excluded_categories),
        "selected_rated_only": filters.rated,
        "hide_selector": list_hide_selector(request, filters.hide),
        "selected_uncategorized_only": filters.uncategorized,
        "selected_asset_filter_mode": filters.asset_filter_mode,
        "selected_category_filter_mode": filters.category_filter_mode,
        "selected_sort": filters.sort,
        "search_query": filters.q,
        "active_filter_pills": video_active_filter_pills(request, filters),
        "category_filter_count": len(filters.categories)
        + len(filters.excluded_categories)
        + int(filters.uncategorized),
        "filters_clear_href": video_filters_clear_href(request),
        "current_videos_path": current_request_path(request),
        "channel_page": library.page,
        "page": library.page,
        "total_pages": library.total_pages,
        "page_href": page_href_builder(request),
        "filtered_video_count": library.total,
        "video_cards": cards,
        "shorts_feature_flags": shorts_feature_flags(cards),
    }


def channel_periodicity(median_days: float | None) -> str | None:
    """A channel's posting rhythm, from the median days between two publications."""
    if median_days is None:
        return None
    rate_per_week = 7 / median_days
    if rate_per_week >= 1:
        return f"~{format_periodicity_rate(rate_per_week)}/sem"
    return f"~{format_periodicity_rate(30 / median_days)}/mois"


def shorts_feature_flags(cards: list) -> list[bool]:
    """Which shorts of a channel page get a big tile in the mosaic, aligned with `cards`.

    New and 5-star shorts come first, in page order; the rhythm slots (0, 7, 14...) fill in around them. A
    candidate too close to an already big tile stays small (it keeps its badge).
    """
    flags = [False] * len(cards)

    def fits(index: int) -> bool:
        return all(
            abs(index - other) >= SHORTS_FEATURE_MIN_GAP for other, big in enumerate(flags) if big
        )

    for index, card in enumerate(cards):
        if (card.is_new or (card.rating or 0) >= 5) and fits(index):
            flags[index] = True
    for index in range(0, len(cards), SHORTS_FEATURE_RHYTHM):
        if fits(index):
            flags[index] = True
    return flags
