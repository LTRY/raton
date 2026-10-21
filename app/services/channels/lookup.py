from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.channel import Channel


class ChannelNotInLibraryError(ValueError):
    def __init__(self) -> None:
        super().__init__("Chaîne introuvable")


def find_library_channel(db: Session, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise ChannelNotInLibraryError()
    return channel


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
