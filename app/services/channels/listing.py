"""The channel list of /channels: sort, Notées filter, search, fiche counts."""

from sqlalchemy import desc, func, nullslast, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.job import DownloadJob
from app.models.video import Video
from app.services.search import channel_search_rank

CHANNEL_SORTS = ("rating", "activity", "alpha", "added")


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
