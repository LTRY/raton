"""The library list (`/videos`, a channel page, `GET /api/videos`) computed in SQL.

The library holds thousands of fiches: only the displayed page is loaded, and counts are SQL
aggregates (docs/spec/11-interface-html.md, "Temps de chargement des pages").
"""

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from back.models.channel import Channel
from back.models.video import Video
from back.services.common.search import video_search_rank
from back.services.videos.filters import video_asset_kind_condition, video_section_condition


def library_order_by(sort: str) -> tuple:
    if sort == "published":
        return (desc(Video.published_at), desc(Video.downloaded_at), desc(Video.id))
    if sort == "rated":
        return (
            desc(Video.rating),
            desc(Video.published_at),
            desc(Video.downloaded_at),
            desc(Video.id),
        )
    if sort == "views":
        # Ties keep the "imported" order, as the former in-Python stable sort did.
        return (
            desc(func.coalesce(Video.view_count, 0)),
            desc(Video.downloaded_at),
            desc(Video.created_at),
            desc(Video.id),
        )
    return (desc(Video.downloaded_at), desc(Video.created_at), desc(Video.id))


def library_page(
    db: Session, where, sort: str, search_query: str, page: int, page_size: int
) -> tuple[list[Video], int, int, int]:
    """One page of the fiches matching `where`: (videos, page, total_pages, matching count).

    `where` may read `Channel`, which is outer-joined (a fiche inherits its channel's labels).
    """
    with_channel = Video.channel_id == Channel.id
    listed = (
        select(Video)
        .outerjoin(Channel, with_channel)
        .where(where)
        .options(selectinload(Video.channel))
        .order_by(*library_order_by(sort))
    )
    if search_query:
        # Word-based, accent-insensitive ranking is Python-only: rank the SQL-filtered candidates.
        ranked = [(video_search_rank(video, search_query), video) for video in db.scalars(listed)]
        # Stable sort: the selected sort still orders videos inside a relevance tier.
        matching = [
            video
            for rank, video in sorted((r for r in ranked if r[0] is not None), key=lambda r: r[0])
        ]
        count = len(matching)
        total_pages = max(1, -(-count // page_size))
        page = min(max(page, 1), total_pages)
        start = (page - 1) * page_size
        return matching[start : start + page_size], page, total_pages, count
    count = db.scalar(select(func.count(Video.id)).outerjoin(Channel, with_channel).where(where))
    total_pages = max(1, -(-count // page_size))
    page = min(page, total_pages)
    videos = list(db.scalars(listed.offset((page - 1) * page_size).limit(page_size)))
    return videos, page, total_pages, count


def library_section_counts(db: Session, in_channel, in_section) -> dict[str, int]:
    """Counters of a channel page (or of the whole library), in one aggregate query."""

    def count_where(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    is_short = video_section_condition("shorts")
    has_media = or_(video_asset_kind_condition("video"), video_asset_kind_condition("audio"))
    local, downloaded, metadata, regular, shorts = db.execute(
        select(
            count_where(in_section),
            count_where(and_(in_section, has_media)),
            count_where(and_(in_section, video_asset_kind_condition("metadata"))),
            count_where(and_(has_media, ~is_short)),
            count_where(and_(has_media, is_short)),
        ).where(in_channel)
    ).one()
    return {
        "local_video_count": local,
        "downloaded_video_count": downloaded,
        "metadata_video_count": metadata,
        "downloaded_regular_video_count": regular,
        "downloaded_short_count": shorts,
    }


def publication_dates(db: Session, in_channel, in_section) -> list:
    return list(
        db.scalars(
            select(Video.published_at).where(
                in_channel, in_section, Video.published_at.is_not(None)
            )
        )
    )
