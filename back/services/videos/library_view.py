"""What the library list (`/videos` and a channel page) shows for a set of filters, without HTTP.

`GET /api/library` builds its filters with `library_filters`, which holds the validation rules,
and calls these functions; the front's `/videos` turns the result into links and markup.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, select, true
from sqlalchemy.orm import Session, selectinload

from back.models.channel import Channel
from back.models.video import Video
from back.services.common.categories import normalize_video_category_label
from back.services.common.durations import format_duration
from back.services.common.library_views import VIDEO_ASSET_KINDS
from back.services.common.search import normalized_search_query
from back.services.common.settings import get_video_library_views
from back.services.common.user_state import channel_states, video_states
from back.services.videos.filters import video_filters_condition, video_section_condition
from back.services.videos.library_query import (
    library_page,
    library_section_counts,
    publication_dates,
)
from back.services.videos.playback import latest_playback_by_video
from back.services.youtube.channel_info import normalized_channel_section

LIBRARY_PAGE_SIZE = 50
LIBRARY_SORTS = ("imported", "published", "views", "rated")
FILTER_MODES = ("and", "or", "not")


@dataclass(frozen=True)
class LibraryFilters:
    channel_id: int | None = None
    # None opens a channel page on its default section (`default_channel_section`).
    section: str | None = None
    sort: str = "imported"
    assets: frozenset[str] = field(default_factory=frozenset)
    categories: frozenset[str] = field(default_factory=frozenset)
    excluded_assets: frozenset[str] = field(default_factory=frozenset)
    excluded_categories: frozenset[str] = field(default_factory=frozenset)
    rated_only: bool = False
    hide_hidden: bool = False
    uncategorized_only: bool = False
    asset_filter_mode: str = "or"
    category_filter_mode: str = "or"
    search_query: str = ""
    page: int = 1


def _labels(values) -> frozenset[str]:
    return frozenset(
        label for label in (normalize_video_category_label(value) for value in values) if label
    )


def _section(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return normalized_channel_section(value)
    except ValueError:
        return None


def library_filters(
    *,
    channel_id: int | None = None,
    section: str | None = None,
    sort: str | None = None,
    assets=(),
    categories=(),
    excluded_assets=(),
    excluded_categories=(),
    rated_only: bool = False,
    hide_hidden: bool = False,
    uncategorized_only: bool = False,
    asset_filter_mode: str | None = None,
    category_filter_mode: str | None = None,
    search_query: str | None = None,
    page: int = 1,
) -> LibraryFilters:
    """Filters from values as a client sent them: unknown file types, sorts, sections and modes
    fall back to their default, category labels are normalized, the search is trimmed."""
    return LibraryFilters(
        channel_id=channel_id,
        section=_section(section),
        sort=sort if sort in LIBRARY_SORTS else ("published" if channel_id else "imported"),
        assets=frozenset(assets) & VIDEO_ASSET_KINDS,
        categories=_labels(categories),
        excluded_assets=frozenset(excluded_assets) & VIDEO_ASSET_KINDS,
        excluded_categories=_labels(excluded_categories),
        rated_only=rated_only,
        hide_hidden=hide_hidden,
        uncategorized_only=uncategorized_only,
        asset_filter_mode=asset_filter_mode if asset_filter_mode in FILTER_MODES else "or",
        category_filter_mode=category_filter_mode if category_filter_mode in FILTER_MODES else "or",
        search_query=normalized_search_query(search_query),
        page=max(page, 1),
    )


@dataclass
class LibraryListing:
    channel: Channel | None
    section: str
    videos: list[Video]
    page: int
    total_pages: int
    filtered_video_count: int
    section_counts: dict[str, int]
    # Only for a channel page: what its posting rhythm is estimated from.
    publication_dates: list[datetime] | None


def default_channel_section(db: Session, user_id: int, channel: Channel | None) -> str:
    """Section a channel page opens on when the URL names none: shorts when the user only
    follows its shorts."""
    if channel is None:
        return "videos"
    state = channel_states(db, user_id, [channel.id])[channel.id]
    if state.auto_shorts_enabled and not state.auto_metadata_enabled:
        return "shorts"
    return "videos"


def library_listing(db: Session, user_id: int, filters: LibraryFilters) -> LibraryListing:
    """The displayed page of fiches and the counts around it, all computed in SQL.

    The library holds thousands of fiches: only the displayed page is loaded
    (docs/spec/11-interface-html.md, "Temps de chargement des pages").
    """
    channel_id = filters.channel_id
    channel = db.get(Channel, channel_id) if channel_id else None
    section = (
        (filters.section or default_channel_section(db, user_id, channel))
        if channel_id
        else "videos"
    )
    in_channel = Video.channel_id == channel_id if channel_id else true()
    in_section = video_section_condition(section) if channel_id else true()
    matches_filters = video_filters_condition(
        set(filters.assets),
        set(filters.categories),
        set(filters.excluded_assets),
        set(filters.excluded_categories),
        filters.rated_only,
        filters.asset_filter_mode,
        filters.category_filter_mode,
        filters.hide_hidden,
        filters.uncategorized_only,
    )
    videos, page, total_pages, count = library_page(
        db,
        user_id,
        and_(in_channel, in_section, matches_filters),
        filters.sort,
        filters.search_query,
        max(filters.page, 1),
        LIBRARY_PAGE_SIZE,
    )
    return LibraryListing(
        channel=channel,
        section=section,
        videos=videos,
        page=page,
        total_pages=total_pages,
        filtered_video_count=count,
        section_counts=library_section_counts(db, in_channel, in_section),
        publication_dates=publication_dates(db, in_channel, in_section) if channel_id else None,
    )


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


def library_cards(db: Session, user_id: int, videos: list[Video]) -> list[dict]:
    """One card per fiche, with the user's state and latest playback (one query each for the
    whole page)."""
    video_ids = [video.id for video in videos]
    playback_by_video_id = latest_playback_by_video(db, user_id, video_ids)
    states = video_states(db, user_id, video_ids)
    cards = [downloaded_video_card(video) for video in videos]
    for card in cards:
        card["playback"] = playback_by_video_id.get(card["video"].id)
        card["state"] = states[card["video"].id]
    return cards


def saved_view_is_active(view: dict, filters: LibraryFilters) -> bool:
    return (
        set(view.get("assets", [])) == filters.assets
        and set(view.get("categories", [])) == filters.categories
        and set(view.get("excluded_assets", [])) == filters.excluded_assets
        and set(view.get("excluded_categories", [])) == filters.excluded_categories
        and bool(view.get("rated")) == filters.rated_only
        and str(view.get("asset_filter_mode") or "or") == filters.asset_filter_mode
        and str(view.get("category_filter_mode") or "or") == filters.category_filter_mode
    )


def library_saved_views(
    db: Session, user_id: int, filters: LibraryFilters | None = None
) -> list[dict]:
    """The user's vues enregistrees, each flagged `active` when it matches the current filters
    (never without filters: a page other than the library list shows none of them)."""
    return [
        {**view, "active": filters is not None and saved_view_is_active(view, filters)}
        for view in get_video_library_views(db, user_id)
    ]


def library_channels(db: Session) -> list[Channel]:
    """Every channel, by name: the channel picker of the library."""
    return list(db.scalars(select(Channel).order_by(Channel.name)))


def publication_interval_days(published_at_values: list[datetime | None]) -> float | None:
    """Median days between two publication days of a channel (a client shows it as a rate per
    week or month); None below two distinct days. Two fiches on one day count half a day apart."""
    dates = sorted({value.date() for value in published_at_values if value}, reverse=True)
    if len(dates) < 2:
        return None
    gaps = sorted(
        max((dates[index] - dates[index + 1]).days, 0.5) for index in range(len(dates) - 1)
    )
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2


def videos_by_ids(db: Session, ids: str, limit: int) -> list[Video]:
    """The fiches of `ids` ("1,2,3", at most `limit`), in that order; unknown ids left out."""
    wanted = [int(part) for part in ids.split(",") if part.strip().isdigit()][:limit]
    if not wanted:
        return []
    by_id = {
        video.id: video
        for video in db.scalars(
            select(Video).where(Video.id.in_(wanted)).options(selectinload(Video.channel))
        )
    }
    return [by_id[video_id] for video_id in wanted if video_id in by_id]
