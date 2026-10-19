"""What the library list (`/videos` and a channel page) shows for a set of filters, without HTTP.

The route reads the query string into `LibraryFilters` and turns the result into links and markup
(`app/web/video_library.py`); another client can call these functions with the same filters.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, select, true
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import Video
from app.services.common.durations import format_duration
from app.services.common.settings import get_video_library_views
from app.services.videos.filters import video_filters_condition, video_section_condition
from app.services.videos.library_query import (
    library_page,
    library_section_counts,
    publication_dates,
)
from app.services.videos.playback import latest_playback_by_video

LIBRARY_PAGE_SIZE = 50


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


def default_channel_section(channel: Channel | None) -> str:
    """Section a channel page opens on when the URL names none."""
    if channel and channel.auto_shorts_enabled and not channel.auto_metadata_enabled:
        return "shorts"
    return "videos"


def library_listing(db: Session, filters: LibraryFilters) -> LibraryListing:
    """The displayed page of fiches and the counts around it, all computed in SQL.

    The library holds thousands of fiches: only the displayed page is loaded
    (docs/spec/11-interface-html.md, "Temps de chargement des pages").
    """
    channel_id = filters.channel_id
    channel = db.get(Channel, channel_id) if channel_id else None
    section = (filters.section or default_channel_section(channel)) if channel_id else "videos"
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


def library_cards(db: Session, videos: list[Video]) -> list[dict]:
    """One card per fiche, with its latest playback (one query for the whole page)."""
    playback_by_video_id = latest_playback_by_video(db, [video.id for video in videos])
    cards = [downloaded_video_card(video) for video in videos]
    for card in cards:
        card["playback"] = playback_by_video_id.get(card["video"].id)
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


def library_saved_views(db: Session, filters: LibraryFilters) -> list[dict]:
    """The vues enregistrees, each flagged `active` when it matches the current filters."""
    return [
        {**view, "active": saved_view_is_active(view, filters)}
        for view in get_video_library_views(db)
    ]


def library_channels(db: Session) -> list[Channel]:
    """Every channel, by name: the channel picker of the library."""
    return list(db.scalars(select(Channel).order_by(Channel.name)))
