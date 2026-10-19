"""Adding and deleting a library channel, shared by the HTML pages and `/api`."""

from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.services.channels.lookup import find_channel
from app.services.channels.profile import remove_channel_profile_files
from app.services.ratings import check_rating
from app.services.settings import get_media_root
from app.services.youtube.channel_info import extract_channel_info


class ChannelAlreadyInLibraryError(Exception):
    def __init__(self, existing: Channel):
        super().__init__(f"{existing.name} est déjà dans la bibliothèque.")
        self.existing = existing


def create_channel(
    db: Session, url: str, rating: int = 1, category_labels: str | None = None
) -> Channel:
    """Resolve `url` on YouTube and add the channel.

    Raises `ChannelNotFoundError` (from yt-dlp) or `ChannelAlreadyInLibraryError`; the same
    channel is matched by its YouTube id, whatever URL it was added with.
    """
    check_rating(rating)
    info = extract_channel_info(url)
    resolved_url = info.get("url", url)
    existing = find_channel(db, resolved_url, info["yt_channel_id"])
    if existing:
        raise ChannelAlreadyInLibraryError(existing)
    channel = Channel(
        url=resolved_url,
        name=info["name"],
        yt_channel_id=info["yt_channel_id"],
        rating=rating,
        category_labels=category_labels,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def delete_channel(db: Session, channel: Channel) -> None:
    # The profile images live outside the channel's rows, so the cascade does not reach them.
    remove_channel_profile_files(get_media_root(db), channel.yt_channel_id)
    db.delete(channel)
    db.commit()
