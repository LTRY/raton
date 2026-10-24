"""`GET /api/library`: the library list as JSON, from the same service as `/videos`."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from back.api.cards import card_reads
from back.api.errors import error_responses
from back.api.users import current_user_id
from back.db.session import get_db
from back.schemas.library import (
    LibraryChannelRead,
    LibraryFiltersRead,
    LibraryPageRead,
    LibraryVideoRead,
    SavedViewRead,
)
from back.services.ingest.channel_exploration import CHANNEL_IMPORT_PROGRESS_LIMIT
from back.services.ingest.identity import ensure_video_channel
from back.services.jobs.downloads import CHANNEL_VIDEO_PAGE_SIZE
from back.services.videos.library_view import (
    LibraryFilters,
    library_filters,
    library_listing,
    library_saved_views,
    publication_interval_days,
    videos_by_ids,
)

router = APIRouter(prefix="/api", tags=["Bibliothèque"])


def filters_read(filters: LibraryFilters) -> LibraryFiltersRead:
    return LibraryFiltersRead(
        channel_id=filters.channel_id,
        sort=filters.sort,
        assets=sorted(filters.assets),
        categories=sorted(filters.categories),
        excluded_assets=sorted(filters.excluded_assets),
        excluded_categories=sorted(filters.excluded_categories),
        rated=filters.rated_only,
        hide_hidden=filters.hide_hidden,
        uncategorized=filters.uncategorized_only,
        asset_filter_mode=filters.asset_filter_mode,
        category_filter_mode=filters.category_filter_mode,
        q=filters.search_query,
    )


def saved_view_read(view: dict) -> SavedViewRead:
    return SavedViewRead(
        name=view["name"],
        active=view["active"],
        assets=view.get("assets", []),
        categories=view.get("categories", []),
        excluded_assets=view.get("excluded_assets", []),
        excluded_categories=view.get("excluded_categories", []),
        rated=bool(view.get("rated")),
        asset_filter_mode=str(view.get("asset_filter_mode") or "or"),
        category_filter_mode=str(view.get("category_filter_mode") or "or"),
    )


@router.get("/library", response_model=LibraryPageRead, responses=error_responses(404, 422))
def get_library(
    channel_id: int | None = None,
    section: str | None = None,
    sort: str | None = None,
    asset: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    exclude_asset: list[str] = Query(default=[]),
    exclude_category: list[str] = Query(default=[]),
    rated: bool = False,
    hide_hidden: bool = False,
    uncategorized: bool = False,
    asset_filter_mode: str | None = None,
    category_filter_mode: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> LibraryPageRead:
    """Same parameter names as `/videos`, but no preset file types: no `asset`, no file filter."""
    filters = library_filters(
        channel_id=channel_id,
        section=section,
        sort=sort,
        assets=asset,
        categories=category,
        excluded_assets=exclude_asset,
        excluded_categories=exclude_category,
        rated_only=rated,
        hide_hidden=hide_hidden,
        uncategorized_only=uncategorized,
        asset_filter_mode=asset_filter_mode,
        category_filter_mode=category_filter_mode,
        search_query=q,
        page=page,
    )
    listing = library_listing(db, user_id, filters)
    if channel_id is not None and listing.channel is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable")
    for video in listing.videos:
        # An old fiche gets its channel (and the channel's labels) the first time it is listed.
        ensure_video_channel(db, video)
    return LibraryPageRead(
        filters=filters_read(filters),
        channel=LibraryChannelRead(id=listing.channel.id, name=listing.channel.name)
        if listing.channel
        else None,
        section=listing.section,
        page=listing.page,
        total_pages=listing.total_pages,
        total=listing.filtered_video_count,
        counts=listing.section_counts,
        items=card_reads(db, user_id, listing.videos),
        saved_views=[saved_view_read(view) for view in library_saved_views(db, user_id, filters)],
        publication_interval_days=publication_interval_days(listing.publication_dates)
        if listing.publication_dates is not None
        else None,
        explore_next_page=listing.section_counts["local_video_count"] // CHANNEL_VIDEO_PAGE_SIZE + 1
        if listing.channel
        else None,
        explore_page_size=CHANNEL_VIDEO_PAGE_SIZE,
    )


@router.get("/library/views", response_model=list[SavedViewRead])
def get_saved_views(
    db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> list[SavedViewRead]:
    """The user's vues enregistrees (none `active`): the Bibliothèque menu of the pages other
    than `/videos`, which gets them with `GET /api/library`."""
    return [saved_view_read(view) for view in library_saved_views(db, user_id)]


@router.get("/library/cards", response_model=list[LibraryVideoRead], responses=error_responses(422))
def get_cards(
    ids: str = "", db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> list[LibraryVideoRead]:
    """The cards of these fiches (`ids=1,2,3`, unknown ones left out), in that order: a channel
    page adds the fiches an exploration imports while it is open."""
    return card_reads(db, user_id, videos_by_ids(db, ids, CHANNEL_IMPORT_PROGRESS_LIMIT))
