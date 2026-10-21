"""The channel list of /channels and `GET /api/channels`: sort, Notées filter, search, page,
fiche counts."""

from dataclasses import dataclass

from sqlalchemy import desc, func, nullslast, select
from sqlalchemy.orm import Session

from back.models.channel import Channel
from back.models.job import DownloadJob
from back.models.video import Video
from back.services.common.search import channel_search_rank
from back.services.youtube.channel_info import search_channels

CHANNEL_SORTS = ("rating", "activity", "alpha", "added")
DEFAULT_CHANNEL_SORT = "activity"
CHANNEL_PAGE_SIZE = 50


@dataclass
class ChannelPage:
    # `channel_entries` rows of the page, each with its `video_count`.
    entries: list[dict]
    page: int
    total_pages: int
    total: int
    sort: str
    # The channels the Notées filter keeps, whatever the search: the count next to the title.
    channel_count: int


def channel_entries(db: Session, sort: str, rated_only: bool, search_query: str) -> list[dict]:
    """Every listed channel with the date of its last playback, in `sort` order.

    With a search, only the matching channels, by relevance tier then `sort`.
    """
    last_played_subquery = (
        select(DownloadJob.channel_id, func.max(DownloadJob.created_at).label("last_played_at"))
        .where(DownloadJob.status == "played", DownloadJob.channel_id.is_not(None))
        .group_by(DownloadJob.channel_id)
        .subquery()
    )
    last_played = nullslast(desc(last_played_subquery.c.last_played_at))
    if sort == "rating":
        ordering = (desc(Channel.rating), last_played, Channel.name)
    elif sort == "alpha":
        ordering = (Channel.name, desc(Channel.rating), last_played)
    elif sort == "added":
        ordering = (desc(Channel.created_at), desc(Channel.id))
    else:
        ordering = (last_played, desc(Channel.rating), Channel.name)
    query = (
        select(Channel, last_played_subquery.c.last_played_at)
        .outerjoin(last_played_subquery, Channel.id == last_played_subquery.c.channel_id)
        .order_by(*ordering)
    )
    if rated_only:
        query = query.where(Channel.rating > 0)
    entries = [
        {"channel": channel, "last_played_at": last_played_at}
        for channel, last_played_at in db.execute(query)
    ]
    if search_query:
        ranked = [(channel_search_rank(entry["channel"], search_query), entry) for entry in entries]
        # Stable sort: the selected sort still orders channels inside a relevance tier.
        entries = [
            entry
            for rank, entry in sorted((r for r in ranked if r[0] is not None), key=lambda r: r[0])
        ]
    return entries


def video_counts_by_channel(db: Session, channel_ids: list[int]) -> dict[int, int]:
    """How many fiches each of these channels has; asked for the displayed page only."""
    if not channel_ids:
        return {}
    return dict(
        db.execute(
            select(Video.channel_id, func.count(Video.id))
            .where(Video.channel_id.in_(channel_ids))
            .group_by(Video.channel_id)
        ).all()
    )


def channels_by_yt_id(db: Session, yt_channel_ids: list[str]) -> dict[str, Channel]:
    return {
        channel.yt_channel_id: channel
        for channel in db.scalars(select(Channel).where(Channel.yt_channel_id.in_(yt_channel_ids)))
    }


def channel_page(
    db: Session, sort: str | None, rated_only: bool, search_query: str, page: int
) -> ChannelPage:
    """One page of `channel_entries`; an unknown sort falls back to the default one.

    The whole list is sorted in Python (the search ranks in Python), which stays cheap: a library
    holds hundreds of channels, not thousands of fiches. Fiches are counted for the page only.
    """
    sort = sort if sort in CHANNEL_SORTS else DEFAULT_CHANNEL_SORT
    entries = channel_entries(db, sort, rated_only, search_query)
    total_pages = max(1, -(-len(entries) // CHANNEL_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * CHANNEL_PAGE_SIZE
    page_entries = entries[start : start + CHANNEL_PAGE_SIZE]
    counts = video_counts_by_channel(db, [entry["channel"].id for entry in page_entries])
    for entry in page_entries:
        entry["video_count"] = counts.get(entry["channel"].id, 0)
    count_query = select(func.count(Channel.id))
    if rated_only:
        count_query = count_query.where(Channel.rating > 0)
    return ChannelPage(
        entries=page_entries,
        page=page,
        total_pages=total_pages,
        total=len(entries),
        sort=sort,
        channel_count=db.scalar(count_query) or 0,
    )


class YoutubeSearchError(ValueError):
    pass


def youtube_channel_candidates(db: Session, query: str) -> list[dict]:
    """YouTube channels matching a free-text name, each with the library's channel when it is
    already there (`existing`, else None); raises `YoutubeSearchError` when YouTube fails."""
    query = query.strip()
    if not query:
        return []
    try:
        results = search_channels(query)
    except Exception as exc:
        raise YoutubeSearchError(f"Recherche YouTube impossible : {exc}") from exc
    known = channels_by_yt_id(db, [result["yt_channel_id"] for result in results])
    return [{**result, "existing": known.get(result["yt_channel_id"])} for result in results]
