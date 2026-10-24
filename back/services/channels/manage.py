"""Adding and deleting a library channel, its categories (shared) and a user's cloches, shared by
the HTML pages and `/api`."""

import logging

from sqlalchemy.orm import Session

from back.core.logging import log_event
from back.models.channel import Channel
from back.services.channels.lookup import find_channel
from back.services.channels.profile import remove_channel_profile_files
from back.services.common.categories import serialized_category_labels
from back.services.common.ratings import check_rating
from back.services.common.settings import add_video_category_labels, get_media_root
from back.services.common.user_state import channel_state, channel_states
from back.services.youtube.channel_info import extract_channel_info

logger = logging.getLogger(__name__)
# The stars of a channel for the user who adds it, unless they choose others: a channel nobody
# rated has 0 and stays out of the Notées filter.
ADDED_CHANNEL_RATING = 1


class ChannelAlreadyInLibraryError(Exception):
    def __init__(self, existing: Channel):
        super().__init__(f"{existing.name} est déjà dans la bibliothèque.")
        self.existing = existing


def create_channel(
    db: Session,
    user_id: int,
    url: str,
    rating: int = ADDED_CHANNEL_RATING,
    category_labels: list[str] | None = None,
) -> Channel:
    """Resolve `url` on YouTube and add the channel, with the user's `rating`.

    Raises `ChannelNotFoundError` (from yt-dlp) or `ChannelAlreadyInLibraryError`; the same
    channel is matched by its YouTube id, whatever URL it was added with.
    """
    check_rating(rating)
    info = extract_channel_info(url)
    return add_resolved_channel(
        db,
        user_id,
        info.get("url", url),
        info["name"],
        info["yt_channel_id"],
        rating,
        category_labels,
    )


def add_resolved_channel(
    db: Session,
    user_id: int,
    url: str,
    name: str,
    yt_channel_id: str,
    rating: int = ADDED_CHANNEL_RATING,
    category_labels: list[str] | None = None,
) -> Channel:
    """Add a channel YouTube already described, with the user's `rating`; raises
    `ChannelAlreadyInLibraryError`."""
    existing = find_channel(db, url, yt_channel_id)
    if existing:
        raise ChannelAlreadyInLibraryError(existing)
    channel = Channel(
        url=url,
        name=name,
        yt_channel_id=yt_channel_id,
        category_labels=serialized_category_labels(category_labels or []),
    )
    db.add(channel)
    if category_labels:
        add_video_category_labels(db, category_labels)
    db.flush()
    channel_state(db, user_id, channel.id).rating = rating
    db.commit()
    db.refresh(channel)
    return channel


def delete_channel(db: Session, channel: Channel) -> None:
    # The profile images live outside the channel's rows, so the cascade does not reach them.
    remove_channel_profile_files(get_media_root(db), channel.yt_channel_id)
    db.delete(channel)
    db.commit()


def set_channel_categories(db: Session, channel: Channel, labels: list[str]) -> None:
    """Store the channel's labels and give them to its fiches that have none of their own."""
    category_labels = serialized_category_labels(labels)
    channel.category_labels = category_labels
    add_video_category_labels(db, labels)
    if category_labels:
        for video in channel.videos:
            if not video.category_labels:
                video.category_labels = category_labels
    db.commit()


def bell_section(section: str) -> str:
    return "shorts" if section in {"short", "shorts"} else "videos"


def bell_section_label(section: str) -> str:
    return "shorts" if section == "shorts" else "vidéos"


def _bell(section: str) -> str:
    return "auto_shorts_enabled" if section == "shorts" else "auto_metadata_enabled"


def set_channel_bell(
    db: Session, user_id: int, channel: Channel, section: str, enabled: bool
) -> bool:
    """Set the user's cloche of `section` ("videos" or "shorts"); returns whether it was just
    turned on.

    A cloche turned on syncs the existing catalogue: the caller queues that import.
    """
    state = channel_state(db, user_id, channel.id)
    switched_on = enabled and not getattr(state, _bell(section))
    setattr(state, _bell(section), enabled)
    db.commit()
    log_event(
        logger,
        "channel.bell",
        channel_id=channel.id,
        user_id=user_id,
        section=section,
        enabled=enabled,
    )
    return switched_on


def toggle_channel_bell(db: Session, user_id: int, channel: Channel, section: str) -> bool:
    """Switch the user's cloche of `section`; returns whether it is now on."""
    state = channel_states(db, user_id, [channel.id])[channel.id]
    return set_channel_bell(db, user_id, channel, section, not getattr(state, _bell(section)))
