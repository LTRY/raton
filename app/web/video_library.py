from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import String, and_, func, literal, or_, true

from app.models.channel import Channel
from app.models.video import Video
from app.services.yt import normalized_channel_section
from app.web.formatting import format_duration
from app.web.shared import (
    normalize_category_label,
    templates,
    video_category_labels,
    video_metadata,
)

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


def video_asset_kinds(video: Video) -> set[str]:
    kinds = set()
    if "/shorts/" in video.url:
        kinds.add("shorts")
    if video.audio_path:
        kinds.add("audio")
    if video.video_path:
        kinds.add("video")
    if video.metadata_path or video.media_type == "metadata":
        kinds.add("metadata")
    if video.transcript_path:
        kinds.add("transcript")
    if video.imported_via_form:
        kinds.add("imported")
    return kinds


def video_has_downloaded_media(video: Video) -> bool:
    return bool(video.video_path or video.audio_path)


def video_is_short(video: Video) -> bool:
    return "/shorts/" in video.url


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
        normalize_category_label(label)
        for label in request.query_params.getlist("category")
        if normalize_category_label(label)
    }


def selected_video_excluded_asset_filters(request: Request) -> set[str]:
    valid_filters = {option["kind"] for option in VIDEO_ASSET_FILTER_OPTIONS}
    return {
        asset for asset in request.query_params.getlist("exclude_asset") if asset in valid_filters
    }


def selected_video_excluded_category_filters(request: Request) -> set[str]:
    return {
        normalize_category_label(label)
        for label in request.query_params.getlist("exclude_category")
        if normalize_category_label(label)
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


VIDEO_LIST_STATES = ("watched", "unwatched", "hidden")


def video_auto_list_state(playback: dict | None, is_replay_category: bool) -> str:
    """État déduit de la seule progression de lecture, sans forçage manuel."""
    if playback and playback.get("is_completed") and not is_replay_category:
        return "watched"
    return "normal"


def video_list_state(video: Video, playback: dict | None, is_replay_category: bool) -> str:
    """État de grisage effectif d'une carte vidéo : normal, watched ou hidden."""
    stored = video.list_state
    if stored == "hidden":
        return "hidden"
    if stored == "watched":
        return "watched"
    if stored == "unwatched":
        return "normal"
    return video_auto_list_state(playback, is_replay_category)


templates.env.globals["video_auto_list_state"] = video_auto_list_state


templates.env.globals["video_list_state"] = video_list_state


def video_matches_filters(
    video: Video,
    asset_filters: set[str],
    category_filters: set[str],
    excluded_asset_filters: set[str],
    excluded_category_filters: set[str],
    rated_only: bool,
    asset_filter_mode: str,
    category_filter_mode: str,
    hide_hidden: bool = False,
    uncategorized_only: bool = False,
) -> bool:
    if hide_hidden and video.list_state == "hidden":
        return False
    video_assets = video_asset_kinds(video)
    video_categories = set(video_category_labels(video))
    if uncategorized_only and video_categories:
        return False
    if excluded_asset_filters.intersection(video_assets):
        return False
    if excluded_category_filters.intersection(video_categories):
        return False
    if asset_filter_mode == "not":
        if asset_filters.intersection(video_assets):
            return False
        asset_filters = set()
    if category_filter_mode == "not":
        if category_filters.intersection(video_categories):
            return False
        category_filters = set()
    asset_conditions = [asset in video_assets for asset in asset_filters]
    if rated_only:
        asset_conditions.append(video.rating > 0)
    category_conditions = [category in video_categories for category in category_filters]
    groups = []
    if asset_conditions:
        if asset_filter_mode == "and":
            groups.append(all(asset_conditions))
        elif asset_filter_mode == "not":
            groups.append(not any(asset_conditions))
        else:
            groups.append(any(asset_conditions))
    if category_conditions:
        if category_filter_mode == "and":
            groups.append(all(category_conditions))
        elif category_filter_mode == "not":
            groups.append(not any(category_conditions))
        else:
            groups.append(any(category_conditions))
    if not groups:
        return True
    return all(groups)


def _present(column):
    """SQL twin of Python truthiness for a nullable text column: neither NULL nor empty."""
    return and_(column.is_not(None), column != "")


def video_asset_kind_condition(kind: str):
    """SQL twin of `kind in video_asset_kinds(video)`; never NULL, so it can be negated."""
    if kind == "shorts":
        return Video.url.contains("/shorts/", autoescape=True)
    if kind == "audio":
        return _present(Video.audio_path)
    if kind == "video":
        return _present(Video.video_path)
    if kind == "metadata":
        return or_(_present(Video.metadata_path), Video.media_type == "metadata")
    if kind == "transcript":
        return _present(Video.transcript_path)
    if kind == "imported":
        return Video.imported_via_form.is_(True)
    raise ValueError(f"Unknown asset kind: {kind}")


def _effective_category_labels():
    """A video's own labels, or its channel's when it has none (needs `Channel` outer-joined)."""
    return func.coalesce(func.nullif(Video.category_labels, ""), Channel.category_labels, "")


def video_uncategorized_condition():
    """SQL twin of `not video_category_labels(video)`, once the channel's labels are inherited."""
    return _effective_category_labels() == ""


def video_category_condition(label: str):
    """SQL twin of `label in video_category_labels(video)`, once the channel's labels are inherited.

    Needs `Channel` outer-joined on `Video.channel_id`: a video without labels of its own shows its channel's
    (`ensure_video_channel` persists that copy when the video is displayed). Stored labels are already
    normalized (`serialized_category_labels`), so a delimited substring match is enough.
    """
    delimited = func.lower(
        func.replace(literal(",", String) + _effective_category_labels() + ",", ", ", ",")
    )
    return delimited.contains(f",{label},", autoescape=True)


def _any_of(conditions: list):
    return or_(*conditions) if conditions else None


def video_filters_condition(
    asset_filters: set[str],
    category_filters: set[str],
    excluded_asset_filters: set[str],
    excluded_category_filters: set[str],
    rated_only: bool,
    asset_filter_mode: str,
    category_filter_mode: str,
    hide_hidden: bool = False,
    uncategorized_only: bool = False,
):
    """SQL twin of `video_matches_filters`: keep the two in step (tests/test_videos_sql_filters.py)."""
    conditions = []
    if hide_hidden:
        conditions.append(or_(Video.list_state.is_(None), Video.list_state != "hidden"))
    if uncategorized_only:
        conditions.append(video_uncategorized_condition())
    excluded_assets = _any_of(
        [video_asset_kind_condition(kind) for kind in sorted(excluded_asset_filters)]
    )
    if excluded_assets is not None:
        conditions.append(~excluded_assets)
    excluded_categories = _any_of(
        [video_category_condition(label) for label in sorted(excluded_category_filters)]
    )
    if excluded_categories is not None:
        conditions.append(~excluded_categories)
    if asset_filter_mode == "not":
        negated = _any_of([video_asset_kind_condition(kind) for kind in sorted(asset_filters)])
        if negated is not None:
            conditions.append(~negated)
        asset_filters = set()
    if category_filter_mode == "not":
        negated = _any_of([video_category_condition(label) for label in sorted(category_filters)])
        if negated is not None:
            conditions.append(~negated)
        category_filters = set()
    asset_conditions = [video_asset_kind_condition(kind) for kind in sorted(asset_filters)]
    if rated_only:
        asset_conditions.append(Video.rating > 0)
    category_conditions = [video_category_condition(label) for label in sorted(category_filters)]
    for group_conditions, mode in (
        (asset_conditions, asset_filter_mode),
        (category_conditions, category_filter_mode),
    ):
        if not group_conditions:
            continue
        if mode == "and":
            conditions.append(and_(*group_conditions))
        elif mode == "not":
            conditions.append(~or_(*group_conditions))
        else:
            conditions.append(or_(*group_conditions))
    return and_(*conditions) if conditions else true()


def video_section_condition(section: str):
    """SQL twin of `video_matches_channel_section`."""
    is_short = Video.url.contains("/shorts/", autoescape=True)
    return is_short if section == "shorts" else ~is_short


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


def video_library_view_is_active(
    view: dict,
    selected_asset_filters: set[str],
    selected_category_filters: set[str],
    selected_excluded_asset_filters: set[str],
    selected_excluded_category_filters: set[str],
    selected_rated_only: bool,
    selected_asset_filter_mode: str,
    selected_category_filter_mode: str,
) -> bool:
    return (
        set(view.get("assets", [])) == selected_asset_filters
        and set(view.get("categories", [])) == selected_category_filters
        and set(view.get("excluded_assets", [])) == selected_excluded_asset_filters
        and set(view.get("excluded_categories", [])) == selected_excluded_category_filters
        and bool(view.get("rated")) == selected_rated_only
        and str(view.get("asset_filter_mode") or "or") == selected_asset_filter_mode
        and str(view.get("category_filter_mode") or "or") == selected_category_filter_mode
    )


def normalized_channel_id(channel_id: int | str | None) -> int | None:
    if channel_id in (None, ""):
        return None
    return int(channel_id)


def default_channel_section(channel: Channel | None) -> str:
    """Section a channel page opens on when the URL names none."""
    if channel and channel.auto_shorts_enabled and not channel.auto_metadata_enabled:
        return "shorts"
    return "videos"


def selected_channel_section(
    request: Request, selected_channel_id: int | None = None, default: str = "videos"
) -> str:
    if not selected_channel_id:
        return "videos"
    try:
        return normalized_channel_section(request.query_params.get("section", default))
    except ValueError:
        return default


def video_matches_channel_section(video: Video, section: str) -> bool:
    is_short = "/shorts/" in video.url
    return is_short if section == "shorts" else not is_short


def downloaded_video_card(video: Video) -> dict:
    # No file read here: a list holds up to a hundred cards and metadata.json is a ~140 KB dump.
    return {
        "downloaded": True,
        "video": video,
        "title": video.title,
        "channel_id": video.channel.id if video.channel else None,
        "channel_name": video.channel.name if video.channel else None,
        "published_at": video.published_at,
        "media_type": video.media_type,
        "file_size_bytes": video.file_size_bytes,
        "duration": format_duration(video.duration_seconds),
        "transcript_path": video.transcript_path,
        "transcript_status": video.transcript_status,
        "video_path": video.video_path,
        "audio_path": video.audio_path,
        "thumbnail_path": video.thumbnail_path,
    }


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
