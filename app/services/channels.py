from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.video import Video


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


def find_channel(db: Session, url: str | None, yt_channel_id: str | None) -> Channel | None:
    """The library channel already holding this YouTube channel, if any.

    The same channel is reachable through several URLs (@handle, /channel/UC...),
    so the YouTube id is what identifies it; the URL only covers rows without one.
    """
    conditions = []
    if yt_channel_id:
        conditions.append(Channel.yt_channel_id == yt_channel_id)
    if url:
        conditions.append(Channel.url == url)
    if not conditions:
        return None
    return db.scalar(select(Channel).where(or_(*conditions)).order_by(Channel.id))
