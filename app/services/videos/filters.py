"""Which fiches a library list keeps: the filters in Python (`video_matches_filters`) and their SQL twin
(`video_filters_condition`), kept in step by tests/test_videos_sql_filters.py."""

from sqlalchemy import String, and_, func, literal, or_, true

from app.models.channel import Channel
from app.models.video import Video
from app.services.common.categories import parse_video_category_labels


def video_category_labels(video: Video) -> list[str]:
    return parse_video_category_labels(getattr(video, "category_labels", None))


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


def video_matches_channel_section(video: Video, section: str) -> bool:
    is_short = "/shorts/" in video.url
    return is_short if section == "shorts" else not is_short


def followed_video_condition():
    """SQL condition: the video's kind (video or short) has its bell on for its channel.

    Needs `Channel` joined on `Video.channel_id`. Shared by the Nouveautés page and Raton's
    new-video count so both announce the same set.
    """
    is_short = Video.url.contains("/shorts/")
    return or_(
        and_(Channel.auto_metadata_enabled.is_(True), ~is_short),
        and_(Channel.auto_shorts_enabled.is_(True), is_short),
    )
