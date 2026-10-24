"""`/api/settings`: the settings `/settings` edits that a client can read and change."""

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from back.api.curfew import curfew_read
from back.api.errors import error_responses
from back.api.users import current_user_id
from back.db.session import get_db
from back.schemas.settings import (
    CategoryStyleRead,
    SettingsRead,
    SettingsUpdate,
    SponsorCategoryRead,
)
from back.services.common.settings import (
    SPONSOR_SEGMENT_CATEGORY_CHOICES,
    SPONSOR_SEGMENT_CATEGORY_LABELS,
    get_auto_notes_enabled,
    get_auto_notes_excluded_category_labels,
    get_global_quota_bytes,
    get_llm_provider_display_label,
    get_media_root,
    get_no_progress_category_labels,
    get_screen_time_limits,
    get_sponsor_segment_categories,
    get_sponsor_skip_enabled,
    get_video_category_label_styles,
    get_video_category_labels,
    get_video_library_views,
    save_settings,
)

router = APIRouter(prefix="/api", tags=["Réglages"])


@router.get("/categories", response_model=list[CategoryStyleRead])
def list_categories(db: Session = Depends(get_db)) -> list[dict]:
    """The video categories with their colours, in their order: what a page needs to colour labels
    and offer category choices, without reading every setting."""
    return get_video_category_label_styles(db)


@router.get("/settings", response_model=SettingsRead)
def read_settings(
    db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> SettingsRead:
    return SettingsRead(
        media_root=str(get_media_root(db)),
        global_quota_bytes=get_global_quota_bytes(db),
        video_category_labels=get_video_category_labels(db),
        video_category_label_styles=get_video_category_label_styles(db),
        video_library_views=get_video_library_views(db, user_id),
        no_progress_category_labels=get_no_progress_category_labels(db),
        auto_notes_enabled=get_auto_notes_enabled(db),
        auto_notes_excluded_category_labels=get_auto_notes_excluded_category_labels(db),
        sponsor_segment_categories=get_sponsor_segment_categories(db),
        sponsor_skip_enabled=get_sponsor_skip_enabled(db),
        sponsor_segment_category_choices=[
            SponsorCategoryRead(value=value, label=SPONSOR_SEGMENT_CATEGORY_LABELS[value])
            for value in SPONSOR_SEGMENT_CATEGORY_CHOICES
        ],
        screen_time_limits=get_screen_time_limits(db, user_id),
        curfew=curfew_read(db),
        llm_provider_label=get_llm_provider_display_label(),
    )


@router.put("/settings", response_model=SettingsRead, responses=error_responses(422))
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(current_user_id),
) -> SettingsRead:
    # save_settings normalizes labels, colours and saved views itself.
    save_settings(
        db,
        user_id,
        media_root=str(Path(payload.media_root).expanduser())
        if payload.media_root is not None
        else None,
        global_quota_bytes=payload.global_quota_bytes,
        category_labels=payload.video_category_labels,
        category_label_styles=payload.video_category_label_styles,
        library_views=payload.video_library_views,
        no_progress_category_labels=payload.no_progress_category_labels,
        auto_notes_enabled=payload.auto_notes_enabled,
        auto_notes_excluded_category_labels=payload.auto_notes_excluded_category_labels,
        sponsor_segment_categories=payload.sponsor_segment_categories,
        sponsor_skip_enabled=payload.sponsor_skip_enabled,
        screen_time_today_minutes=payload.screen_time_today_minutes.model_dump()
        if payload.screen_time_today_minutes
        else None,
        curfew_enabled=payload.curfew_enabled,
        curfew_start=payload.curfew_start,
        curfew_end=payload.curfew_end,
    )
    return read_settings(db, user_id)
