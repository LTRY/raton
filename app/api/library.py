"""`GET /api/library`: the library list as JSON, from the same service as `/videos`."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.session import get_db
from app.schemas.library import (
    CardPlaybackRead,
    LibraryChannelRead,
    LibraryFiltersRead,
    LibraryPageRead,
    LibraryVideoRead,
    SavedViewRead,
)
from app.schemas.video import VideoRead
from app.services.videos.library_view import (
    LibraryFilters,
    library_cards,
    library_filters,
    library_listing,
    library_saved_views,
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


def card_read(card: dict) -> LibraryVideoRead:
    video = card["video"]
    playback = card["playback"]
    return LibraryVideoRead(
        **VideoRead.model_validate(video).model_dump(),
        channel_name=card["channel_name"],
        duration_seconds=video.duration_seconds,
        view_count=video.view_count,
        is_new=video.is_new,
        list_state=video.list_state,
        # Both paths can be set at once: check each column, never media_type.
        has_video=video.video_path is not None,
        has_audio=video.audio_path is not None,
        has_thumbnail=video.thumbnail_path is not None,
        playback=CardPlaybackRead(**playback) if playback else None,
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
    listing = library_listing(db, filters)
    if channel_id is not None and listing.channel is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable")
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
        items=[card_read(card) for card in library_cards(db, listing.videos)],
        saved_views=[
            SavedViewRead(
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
            for view in library_saved_views(db, filters)
        ],
    )
