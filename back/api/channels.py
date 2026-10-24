"""`/api/channels`: reading, adding, editing and deleting channels, and the CSV import of
YouTube subscriptions.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from back.api.errors import error_responses
from back.api.lookups import library_channel
from back.api.users import current_user_id
from back.db.session import get_db
from back.models.channel import Channel
from back.schemas.actions import JobQueuedRead
from back.schemas.channel import (
    BellSection,
    ChannelBellRead,
    ChannelBellUpdate,
    ChannelCategoriesUpdate,
    ChannelCreate,
    ChannelDetailRead,
    ChannelListItemRead,
    ChannelMetadataImport,
    ChannelNameRead,
    ChannelPageRead,
    ChannelProfileRefreshRead,
    ChannelRead,
    ChannelStateRead,
    RatingUpdate,
    SubscriptionRowRead,
    SubscriptionsAddedRead,
    SubscriptionsConfirm,
    SubscriptionsPreviewRead,
    YoutubeChannelRead,
)
from back.services.channels import manage as channel_manage
from back.services.channels.listing import (
    YoutubeSearchError,
    channel_page,
    video_counts_by_channel,
    youtube_channel_candidates,
)
from back.services.channels.manage import (
    ChannelAlreadyInLibraryError,
    set_channel_bell,
    set_channel_categories,
)
from back.services.channels.subscriptions import (
    SubscriptionsCsvError,
    add_subscriptions,
    parse_subscriptions_csv,
    preview_subscriptions,
)
from back.services.common.categories import parse_video_category_labels
from back.services.common.ratings import InvalidRatingError, set_rating
from back.services.common.search import normalized_search_query
from back.services.common.user_state import channel_states
from back.services.jobs.backfills import (
    run_channel_profile_backfill_job,
    run_channel_profile_refresh_job,
)
from back.services.jobs.download_requests import (
    queue_channel_catalog_sync,
    queue_channel_metadata_import,
)
from back.services.jobs.downloads import run_channel_metadata_import_job
from back.services.videos.library_view import library_channels
from back.services.youtube.channel_info import ChannelNotFoundError

router = APIRouter(prefix="/api", tags=["Chaînes"])


def channel_images(channel: Channel) -> dict:
    return {
        "avatar_url": f"/api/channels/{channel.id}/avatar" if channel.avatar_path else None,
        "banner_url": f"/api/channels/{channel.id}/banner" if channel.banner_path else None,
    }


@router.get("/channels", response_model=ChannelPageRead, responses=error_responses(422))
def list_channels(
    sort: str | None = None,
    rated: bool = False,
    q: str | None = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> ChannelPageRead:
    """Same sorts, Notées filter and search as `/channels`; unlike the page, every channel is
    listed unless `rated=true`."""
    listed = channel_page(db, user_id, sort, rated, normalized_search_query(q), page)
    states = channel_states(db, user_id, [entry["channel"].id for entry in listed.entries])
    return ChannelPageRead(
        items=[
            ChannelListItemRead(
                **ChannelRead.of(entry["channel"], states[entry["channel"].id]).model_dump(),
                **channel_images(entry["channel"]),
                metadata_fetched_at=entry["channel"].metadata_fetched_at,
                video_count=entry["video_count"],
                last_played_at=entry["last_played_at"],
            )
            for entry in listed.entries
        ],
        sort=listed.sort,
        page=listed.page,
        total_pages=listed.total_pages,
        total=listed.total,
        channel_count=listed.channel_count,
    )


@router.get(
    "/youtube/channels",
    response_model=list[YoutubeChannelRead],
    responses=error_responses(422, 502),
)
def search_youtube_channels(q: str = "", db: Session = Depends(get_db)) -> list[YoutubeChannelRead]:
    """YouTube channels matching a name, to pick the one to add."""
    try:
        candidates = youtube_channel_candidates(db, q)
    except YoutubeSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        YoutubeChannelRead(
            **{key: value for key, value in candidate.items() if key != "existing"},
            existing=ChannelNameRead(id=candidate["existing"].id, name=candidate["existing"].name)
            if candidate["existing"]
            else None,
        )
        for candidate in candidates
    ]


@router.get("/channels/names", response_model=list[ChannelNameRead])
def list_channel_names(db: Session = Depends(get_db)) -> list[ChannelNameRead]:
    """Every channel of the library by name, for a channel picker."""
    return [ChannelNameRead(id=channel.id, name=channel.name) for channel in library_channels(db)]


@router.get(
    "/channels/{channel_id}", response_model=ChannelDetailRead, responses=error_responses(404, 422)
)
def get_channel(
    channel_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> ChannelDetailRead:
    channel = library_channel(db, channel_id)
    return ChannelDetailRead(
        **ChannelRead.of(
            channel, channel_states(db, user_id, [channel.id])[channel.id]
        ).model_dump(),
        description=channel.description,
        keywords=channel.keyword_list,
        **channel_images(channel),
        metadata_fetched_at=channel.metadata_fetched_at,
        last_scanned_at=channel.last_scanned_at,
        video_count=video_counts_by_channel(db, [channel.id]).get(channel.id, 0),
    )


@router.post(
    "/channels",
    response_model=ChannelRead,
    status_code=201,
    responses=error_responses(400, 404, 409, 422),
)
def create_channel(
    payload: ChannelCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> ChannelRead:
    try:
        channel = channel_manage.create_channel(
            db, user_id, payload.url, rating=payload.rating, category_labels=payload.categories
        )
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChannelAlreadyInLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(run_channel_profile_backfill_job)
    return ChannelRead.of(channel, channel_states(db, user_id, [channel.id])[channel.id])


@router.delete("/channels/{channel_id}", status_code=204, responses=error_responses(404, 422))
def delete_channel(channel_id: int, db: Session = Depends(get_db)) -> None:
    channel = library_channel(db, channel_id)
    channel_manage.delete_channel(db, channel)


def channel_state(db: Session, user_id: int, channel: Channel) -> ChannelStateRead:
    state = channel_states(db, user_id, [channel.id])[channel.id]
    return ChannelStateRead(
        id=channel.id,
        name=channel.name,
        rating=state.rating,
        categories=parse_video_category_labels(channel.category_labels),
        auto_metadata_enabled=state.auto_metadata_enabled,
        auto_shorts_enabled=state.auto_shorts_enabled,
    )


@router.put(
    "/channels/{channel_id}/rating",
    response_model=ChannelStateRead,
    responses=error_responses(400, 404, 422),
)
def update_rating(
    channel_id: int,
    payload: RatingUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> ChannelStateRead:
    """The user's 0 to 5 stars; 400 with the service's message otherwise."""
    channel = library_channel(db, channel_id)
    try:
        set_rating(db, user_id, channel, payload.rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return channel_state(db, user_id, channel)


@router.put(
    "/channels/{channel_id}/categories",
    response_model=ChannelStateRead,
    responses=error_responses(404, 422),
)
def update_categories(
    channel_id: int,
    payload: ChannelCategoriesUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> ChannelStateRead:
    channel = library_channel(db, channel_id)
    set_channel_categories(db, channel, payload.categories)
    return channel_state(db, user_id, channel)


@router.put(
    "/channels/{channel_id}/bells/{section}",
    response_model=ChannelBellRead,
    responses=error_responses(404, 422),
)
def update_bell(
    channel_id: int,
    section: BellSection,
    payload: ChannelBellUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> ChannelBellRead:
    """Set the user's cloche; turning it on syncs the existing catalogue in the background."""
    channel = library_channel(db, channel_id)
    job = None
    if set_channel_bell(db, user_id, channel, section, payload.enabled):
        job = queue_channel_catalog_sync(db, channel, section)
        # The existing catalogue is not news: the job marks nothing Nouveau.
        background_tasks.add_task(run_channel_metadata_import_job, job.id, channel.id, 1, section)
    return ChannelBellRead(
        channel=channel_state(db, user_id, channel),
        job=JobQueuedRead.from_job(job) if job else None,
    )


@router.post(
    "/channels/{channel_id}/import-metadata",
    response_model=JobQueuedRead,
    status_code=202,
    responses=error_responses(404, 422),
)
def import_metadata(
    channel_id: int,
    background_tasks: BackgroundTasks,
    payload: ChannelMetadataImport | None = None,
    db: Session = Depends(get_db),
) -> JobQueuedRead:
    """Import one page of the channel's videos or shorts (metadata only)."""
    channel = library_channel(db, channel_id)
    payload = payload or ChannelMetadataImport()
    job = queue_channel_metadata_import(db, channel, payload.section)
    background_tasks.add_task(
        run_channel_metadata_import_job, job.id, channel.id, payload.page, payload.section
    )
    return JobQueuedRead.from_job(job)


@router.post(
    "/channels/{channel_id}/refresh-profile",
    response_model=ChannelProfileRefreshRead,
    status_code=202,
    responses=error_responses(404, 422),
)
def refresh_profile(
    channel_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> ChannelProfileRefreshRead:
    channel = library_channel(db, channel_id)
    background_tasks.add_task(run_channel_profile_refresh_job, channel.id)
    return ChannelProfileRefreshRead(
        status="started",
        message=f"Rafraîchissement du profil de {channel.name} lancé en arrière-plan.",
    )


@router.post(
    "/channels/import-csv",
    response_model=SubscriptionsPreviewRead,
    responses=error_responses(400, 422),
)
def preview_subscriptions_csv(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> SubscriptionsPreviewRead:
    """Read a Google Takeout subscriptions CSV; writes nothing (confirm with the tokens)."""
    try:
        parsed_rows = parse_subscriptions_csv(file.file.read())
    except SubscriptionsCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = preview_subscriptions(db, parsed_rows)
    new_count = sum(1 for row in rows if not row["already_imported"])
    return SubscriptionsPreviewRead(
        rows=[SubscriptionRowRead(**row) for row in rows],
        new_count=new_count,
        existing_count=len(rows) - new_count,
    )


@router.post(
    "/channels/import-csv/confirm",
    response_model=SubscriptionsAddedRead,
    responses=error_responses(422),
)
def confirm_subscriptions_csv(
    payload: SubscriptionsConfirm,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> SubscriptionsAddedRead:
    added = add_subscriptions(db, user_id, payload.tokens)
    if added:
        background_tasks.add_task(run_channel_profile_backfill_job)
    return SubscriptionsAddedRead(added=added)
