"""Which fiches a library list keeps: the filters in Python (`video_matches_filters`) and their SQL twin
(`video_filters_condition`), kept in step by tests/test_videos_sql_filters.py.

The Écartée state and the stars are the user's own: the Python filter takes their state row, the
SQL one reads the `UserVideo` row the query outer-joins (`video_state_join`)."""

from sqlalchemy import String, and_, func, literal, or_, true

from back.core.config import local_media_path
from back.models.channel import Channel
from back.models.user import UserVideo
from back.models.video import Video
from back.services.common.categories import parse_video_category_labels
from back.services.common.user_state import (
    channel_shorts_bell,
    channel_videos_bell,
    video_rating,
)
from back.services.videos.documents import NOTES_FILE

# What a list leaves out, from the 3-icon selector (docs/spec/11-interface-html.md): nothing, the
# Vu fiches, or the Vu and the Écartée ones.
LIST_HIDES = ("none", "watched", "watched_hidden")


def list_hide(value: str | None, default: str) -> str:
    return value if value in LIST_HIDES else default


def video_category_labels(video: Video) -> list[str]:
    return parse_video_category_labels(getattr(video, "category_labels", None))


def video_badges(video: Video, is_new: bool) -> list[str]:
    """What a fiche holds, in the order the badges show: new (for the user), audio, video,
    metadata, transcript, notes, imported (manual import)."""
    kinds = []
    if is_new:
        kinds.append("new")
    if video.audio_path:
        kinds.append("audio")
    if video.video_path:
        kinds.append("video")
    if video.metadata_path or video.media_type == "metadata":
        kinds.append("metadata")
    if video.transcript_path:
        kinds.append("transcript")
        if local_media_path(video.transcript_path).with_name(NOTES_FILE).is_file():
            kinds.append("notes")
    if video.imported_via_form:
        kinds.append("imported")
    return kinds


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


def video_matches_filters(
    video: Video,
    state: UserVideo,
    asset_filters: set[str],
    category_filters: set[str],
    excluded_asset_filters: set[str],
    excluded_category_filters: set[str],
    rated_only: bool,
    asset_filter_mode: str,
    category_filter_mode: str,
    hide: str = "none",
    uncategorized_only: bool = False,
    no_progress_labels: frozenset[str] = frozenset(),
) -> bool:
    if hide != "none" and video_is_watched(video, state, no_progress_labels):
        return False
    if hide == "watched_hidden" and state.list_state == "hidden":
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
        asset_conditions.append(state.rating > 0)
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


def video_is_watched(video: Video, state: UserVideo, no_progress_labels: frozenset[str]) -> bool:
    """Vu for the user, as a list filters it: marked Vu by hand, or their `watched_at` set by the
    90 % rule while not forced non-vu nor Écartée, outside a "no progress bar" category
    (replayed, never done)."""
    if state.list_state == "watched":
        return True
    if state.list_state is not None or state.watched_at is None:
        return False
    return not no_progress_labels.intersection(video_category_labels(video))


def video_watched_condition(no_progress_labels: frozenset[str]):
    """SQL twin of `video_is_watched`; never NULL, so it can be negated. Needs `UserVideo`
    (`video_state_join`) and `Channel` outer-joined (see `video_category_condition`)."""
    auto = and_(UserVideo.list_state.is_(None), UserVideo.watched_at.is_not(None))
    replay = _any_of([video_category_condition(label) for label in sorted(no_progress_labels)])
    if replay is not None:
        auto = and_(auto, ~replay)
    return or_(func.coalesce(UserVideo.list_state, "") == "watched", auto)


def video_list_hide_condition(hide: str, no_progress_labels: frozenset[str]):
    """The fiches a list keeps for its `hide` level (`LIST_HIDES`); same joins as
    `video_watched_condition`."""
    conditions = []
    if hide != "none":
        conditions.append(~video_watched_condition(no_progress_labels))
    if hide == "watched_hidden":
        conditions.append(func.coalesce(UserVideo.list_state, "") != "hidden")
    return and_(true(), *conditions)


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
    hide: str = "none",
    uncategorized_only: bool = False,
    no_progress_labels: frozenset[str] = frozenset(),
):
    """SQL twin of `video_matches_filters`: keep the two in step (tests/test_videos_sql_filters.py).

    Needs `UserVideo` outer-joined with `video_state_join`."""
    conditions = [video_list_hide_condition(hide, no_progress_labels)]
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
        asset_conditions.append(video_rating > 0)
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
    """Shorts (their URL holds `/shorts/`) or the other fiches of a channel page."""
    is_short = Video.url.contains("/shorts/", autoescape=True)
    return is_short if section == "shorts" else ~is_short


def followed_video_condition():
    """SQL condition: the video's kind (video or short) has the user's bell on for its channel.

    Needs `Channel` joined on `Video.channel_id` and `UserChannel` outer-joined with
    `channel_state_join`. Shared by the Nouveautés page and Raton's new-video count so both
    announce the same set.
    """
    is_short = Video.url.contains("/shorts/")
    return or_(
        and_(channel_videos_bell.is_(True), ~is_short),
        and_(channel_shorts_bell.is_(True), is_short),
    )
