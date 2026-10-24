"""The Nouveautés: one stack of the most recent fiches per followed channel, paginated by channel."""

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session, selectinload

from back.models.channel import Channel
from back.models.video import Video
from back.services.videos.filters import followed_video_condition, video_not_hidden_condition

NOUVEAUTES_CHANNEL_PAGE_SIZE = 10
NOUVEAUTES_STACK_SIZE = 10


def nouveautes_stacks(
    db: Session,
    page: int = 1,
    page_size: int = NOUVEAUTES_CHANNEL_PAGE_SIZE,
    show_hidden: bool = False,
) -> tuple[list[tuple[Channel, list[Video]]], int, int]:
    """(stacks, page, total_pages); `page` counts channels, not fiches.

    Already-visited fiches stay listed (this is not a filter on `Video.is_new`). Each bell scopes
    its own kind: a fiche is listed only when the bell matching its kind (video or short) is on
    for its channel. Fiches imported through a playlist land on a channel with no bell and never
    feed this section (see docs/spec/07-youtube-et-telechargements.md). Écartée fiches are left
    out unless `show_hidden`, so a channel whose recent fiches are all Écartée has no stack.
    """
    recency = func.coalesce(Video.published_at, Video.downloaded_at, Video.created_at)
    followed_kind = followed_video_condition()
    if not show_hidden:
        followed_kind = and_(followed_kind, video_not_hidden_condition())
    channel_ids = list(
        db.scalars(
            select(Video.channel_id)
            .join(Channel, Channel.id == Video.channel_id)
            .where(followed_kind)
            .group_by(Video.channel_id)
            .order_by(desc(func.max(recency)))
        )
    )
    total_pages = max(1, -(-len(channel_ids) // page_size))
    page = min(max(page, 1), total_pages)
    stacks = []
    for channel_id in channel_ids[(page - 1) * page_size : page * page_size]:
        channel = db.get(Channel, channel_id)
        if channel is None:
            continue
        videos = list(
            db.scalars(
                select(Video)
                .join(Channel, Channel.id == Video.channel_id)
                .where(Video.channel_id == channel_id)
                .where(followed_kind)
                .options(selectinload(Video.channel))
                .order_by(
                    desc(Video.published_at), desc(Video.downloaded_at), desc(Video.created_at)
                )
                .limit(NOUVEAUTES_STACK_SIZE)
            )
        )
        if videos:
            stacks.append((channel, videos))
    return stacks, page, total_pages
