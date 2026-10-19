from urllib.parse import urlencode

from fastapi import Request

from app.models.video import Video
from app.services.common.categories import normalize_video_category_label
from app.services.videos.documents import read_video_metadata as video_metadata
from app.services.videos.library_view import LibraryFilters
from app.services.videos.list_state import video_auto_list_state, video_list_state
from app.services.youtube.channel_info import normalized_channel_section
from app.web.shared import templates

templates.env.globals["video_auto_list_state"] = video_auto_list_state
templates.env.globals["video_list_state"] = video_list_state

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


def normalized_search_query(value: str | None) -> str:
    """The query as typed, whitespace collapsed — also what the search field echoes back."""
    return " ".join((value or "").split())


def selected_video_asset_filters(
    request: Request, selected_channel_id: int | None = None
) -> set[str]:
    valid_filters = {option["kind"] for option in VIDEO_ASSET_FILTER_OPTIONS}
    if request.query_params.get("asset_filters") != "1":
        if selected_channel_id:
            return set(DEFAULT_CHANNEL_VIDEO_ASSET_FILTERS)
        return set(DEFAULT_VIDEO_ASSET_FILTERS)
    return {asset for asset in request.query_params.getlist("asset") if asset in valid_filters}


def selected_video_category_filters(request: Request) -> set[str]:
    return {
        normalize_video_category_label(label)
        for label in request.query_params.getlist("category")
        if normalize_video_category_label(label)
    }


def selected_video_excluded_asset_filters(request: Request) -> set[str]:
    valid_filters = {option["kind"] for option in VIDEO_ASSET_FILTER_OPTIONS}
    return {
        asset for asset in request.query_params.getlist("exclude_asset") if asset in valid_filters
    }


def selected_video_excluded_category_filters(request: Request) -> set[str]:
    return {
        normalize_video_category_label(label)
        for label in request.query_params.getlist("exclude_category")
        if normalize_video_category_label(label)
    }


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


def query_without(request: Request, remove: list[tuple[str, str | None]]) -> str:
    def matches(key: str, value: str) -> bool:
        return any(rk == key and (rv is None or rv == value) for rk, rv in remove)

    pairs = [
        (key, value) for key, value in request.query_params.multi_items() if not matches(key, value)
    ]
    query = urlencode(pairs)
    return f"{request.url.path}?{query}" if query else request.url.path


def video_filters_clear_href(request: Request) -> str:
    keep_keys = {"channel_id", "section", "sort", "q"}
    pairs = [(key, value) for key, value in request.query_params.multi_items() if key in keep_keys]
    pairs.append(("asset_filters", "1"))
    return f"{request.url.path}?{urlencode(pairs)}"


def video_active_filter_pills(
    request: Request,
    selected_asset_filters: set[str],
    selected_excluded_asset_filters: set[str],
    selected_category_filters: set[str],
    selected_excluded_category_filters: set[str],
    selected_rated_only: bool,
    selected_hide_hidden: bool = False,
    selected_channel_id: int | None = None,
    selected_uncategorized_only: bool = False,
) -> list[dict]:
    pills = []
    # A channel page selects every file type by default: that is "no filter", so it shows no pill.
    if selected_channel_id and selected_asset_filters == DEFAULT_CHANNEL_VIDEO_ASSET_FILTERS:
        selected_asset_filters = set()
    if selected_rated_only:
        pills.append(
            {
                "label": "★ Notées",
                "kind": "include",
                "href": query_without(request, [("rated", None)]),
            }
        )
    if selected_hide_hidden:
        pills.append(
            {
                "label": "Écartées masquées",
                "kind": "exclude",
                "href": query_without(request, [("hide_hidden", None)]),
            }
        )
    for option in VIDEO_ASSET_FILTER_OPTIONS:
        kind = option["kind"]
        if kind in selected_asset_filters:
            pills.append(
                {
                    "label": option["text"],
                    "kind": "include",
                    "href": query_without(request, [("asset", kind)]),
                }
            )
        if kind in selected_excluded_asset_filters:
            pills.append(
                {
                    "label": option["text"],
                    "kind": "exclude",
                    "href": query_without(request, [("exclude_asset", kind)]),
                }
            )
    if selected_uncategorized_only:
        pills.append(
            {
                "label": "Sans catégorie",
                "kind": "include",
                "href": query_without(request, [("uncategorized", None)]),
            }
        )
    for category in sorted(selected_category_filters):
        pills.append(
            {
                "label": category,
                "kind": "include",
                "href": query_without(request, [("category", category)]),
            }
        )
    for category in sorted(selected_excluded_category_filters):
        pills.append(
            {
                "label": category,
                "kind": "exclude",
                "href": query_without(request, [("exclude_category", category)]),
            }
        )
    return pills


def selected_video_sort(request: Request, selected_channel_id: int | None = None) -> str:
    sort = request.query_params.get("sort")
    if sort in {"imported", "published", "views", "rated"}:
        return sort
    if selected_channel_id:
        return "published"
    return "imported"


def video_view_count(video: Video) -> int:
    try:
        return int(video_metadata(video).get("view_count"))
    except TypeError, ValueError:
        return 0


def video_library_view_path(view: dict, request: Request) -> str:
    params: list[tuple[str, str]] = [("asset_filters", "1")]
    for name in ("channel_id", "section", "sort"):
        value = request.query_params.get(name)
        if value:
            params.append((name, value))
    params.append(("asset_filter_mode", str(view.get("asset_filter_mode") or "or")))
    params.append(("category_filter_mode", str(view.get("category_filter_mode") or "or")))
    for asset in view.get("assets", []):
        params.append(("asset", str(asset)))
    for asset in view.get("excluded_assets", []):
        params.append(("exclude_asset", str(asset)))
    for category in view.get("categories", []):
        params.append(("category", str(category)))
    for category in view.get("excluded_categories", []):
        params.append(("exclude_category", str(category)))
    if view.get("rated"):
        params.append(("rated", "1"))
    return f"/videos?{urlencode(params)}"


def normalized_channel_id(channel_id: int | str | None) -> int | None:
    if channel_id in (None, ""):
        return None
    return int(channel_id)


def requested_channel_section(request: Request) -> str | None:
    """The section named in the URL, or None (absent or unknown) for the channel's default one."""
    section = request.query_params.get("section")
    if section is None:
        return None
    try:
        return normalized_channel_section(section)
    except ValueError:
        return None


def library_filters_from_request(
    request: Request, channel_id: int | str | None, page: int
) -> LibraryFilters:
    selected_channel_id = normalized_channel_id(channel_id)
    return LibraryFilters(
        channel_id=selected_channel_id,
        section=requested_channel_section(request),
        sort=selected_video_sort(request, selected_channel_id),
        assets=frozenset(selected_video_asset_filters(request, selected_channel_id)),
        categories=frozenset(selected_video_category_filters(request)),
        excluded_assets=frozenset(selected_video_excluded_asset_filters(request)),
        excluded_categories=frozenset(selected_video_excluded_category_filters(request)),
        rated_only=request.query_params.get("rated") == "1",
        hide_hidden=request.query_params.get("hide_hidden") == "1",
        uncategorized_only=request.query_params.get("uncategorized") == "1",
        asset_filter_mode=selected_video_filter_mode(request, "asset_filter_mode"),
        category_filter_mode=selected_video_filter_mode(request, "category_filter_mode"),
        search_query=normalized_search_query(request.query_params.get("q")),
        page=page,
    )


def shorts_feature_flags(cards: list[dict]) -> list[bool]:
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
        video = card["video"]
        if (video.is_new or (video.rating or 0) >= 5) and fits(index):
            flags[index] = True
    for index in range(0, len(cards), SHORTS_FEATURE_RHYTHM):
        if fits(index):
            flags[index] = True
    return flags
