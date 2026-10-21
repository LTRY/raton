"""`/api` actions on a channel and the CSV import of YouTube subscriptions.

Each route calls the service its HTML form twin calls (`app/web/routes/channels.py`). Listing,
reading, adding and deleting a channel are in `app/api/routes.py`.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.channel import Channel
from app.schemas.actions import JobQueuedRead
from app.schemas.channel import (
    BellSection,
    ChannelBellRead,
    ChannelBellUpdate,
    ChannelCategoriesUpdate,
    ChannelMetadataImport,
    ChannelProfileRefreshRead,
    ChannelStateRead,
    RatingUpdate,
    SubscriptionRowRead,
    SubscriptionsAddedRead,
    SubscriptionsConfirm,
    SubscriptionsPreviewRead,
)
from app.services.channels.manage import set_channel_bell, set_channel_categories
from app.services.channels.subscriptions import (
    SubscriptionsCsvError,
    add_subscriptions,
    parse_subscriptions_csv,
    preview_subscriptions,
)
from app.services.common.categories import parse_video_category_labels
from app.services.common.ratings import InvalidRatingError, set_rating
from app.services.jobs.backfills import (
    run_channel_profile_backfill_job,
    run_channel_profile_refresh_job,
)
from app.services.jobs.downloads import (
    queue_channel_catalog_sync,
    queue_channel_metadata_import,
    run_channel_metadata_import_job,
)

router = APIRouter(prefix="/api")


def library_channel(db: Session, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable")
    return channel


def channel_state(channel: Channel) -> ChannelStateRead:
    return ChannelStateRead(
        id=channel.id,
        name=channel.name,
        rating=channel.rating,
        categories=parse_video_category_labels(channel.category_labels),
        auto_metadata_enabled=channel.auto_metadata_enabled,
        auto_shorts_enabled=channel.auto_shorts_enabled,
    )


@router.put("/channels/{channel_id}/rating", response_model=ChannelStateRead)
def update_rating(
    channel_id: int, payload: RatingUpdate, db: Session = Depends(get_db)
) -> ChannelStateRead:
    """0 to 5 stars; 400 with the service's message otherwise."""
    channel = library_channel(db, channel_id)
    try:
        set_rating(db, channel, payload.rating)
    except InvalidRatingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return channel_state(channel)


@router.put("/channels/{channel_id}/categories", response_model=ChannelStateRead)
def update_categories(
    channel_id: int, payload: ChannelCategoriesUpdate, db: Session = Depends(get_db)
) -> ChannelStateRead:
    channel = library_channel(db, channel_id)
    set_channel_categories(db, channel, payload.categories)
    return channel_state(channel)


@router.put("/channels/{channel_id}/bells/{section}", response_model=ChannelBellRead)
def update_bell(
    channel_id: int,
    section: BellSection,
    payload: ChannelBellUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ChannelBellRead:
    """Set a cloche; turning it on syncs the existing catalogue in the background."""
    channel = library_channel(db, channel_id)
    job = None
    if set_channel_bell(db, channel, section, payload.enabled):
        job = queue_channel_catalog_sync(db, channel, section)
        # The existing catalogue is not news: mark_new stays off.
        background_tasks.add_task(
            run_channel_metadata_import_job, job.id, channel.id, 1, section, False
        )
    return ChannelBellRead(
        channel=channel_state(channel), job=JobQueuedRead.from_job(job) if job else None
    )


@router.post(
    "/channels/{channel_id}/import-metadata", response_model=JobQueuedRead, status_code=202
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


@router.post("/channels/import-csv", response_model=SubscriptionsPreviewRead)
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


@router.post("/channels/import-csv/confirm", response_model=SubscriptionsAddedRead)
def confirm_subscriptions_csv(
    payload: SubscriptionsConfirm,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SubscriptionsAddedRead:
    added = add_subscriptions(db, payload.tokens)
    if added:
        background_tasks.add_task(run_channel_profile_backfill_job)
    return SubscriptionsAddedRead(added=added)
