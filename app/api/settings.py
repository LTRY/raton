"""`/api/settings`: the settings `/settings` edits that a client can read and change."""

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.session import get_db
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.services.common.settings import (
    get_global_quota_bytes,
    get_media_root,
    get_video_category_label_styles,
    get_video_category_labels,
    get_video_library_views,
    save_settings,
)

router = APIRouter(prefix="/api", tags=["Réglages"])


@router.get("/settings", response_model=SettingsRead)
def read_settings(db: Session = Depends(get_db)) -> SettingsRead:
    return SettingsRead(
        media_root=str(get_media_root(db)),
        global_quota_bytes=get_global_quota_bytes(db),
        video_category_labels=get_video_category_labels(db),
        video_category_label_styles=get_video_category_label_styles(db),
        video_library_views=get_video_library_views(db),
    )


@router.put("/settings", response_model=SettingsRead, responses=error_responses(422))
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsRead:
    # save_settings normalizes labels, colours and saved views itself.
    save_settings(
        db,
        media_root=str(Path(payload.media_root).expanduser())
        if payload.media_root is not None
        else None,
        global_quota_bytes=payload.global_quota_bytes,
        category_labels=payload.video_category_labels,
        category_label_styles=payload.video_category_label_styles,
        library_views=payload.video_library_views,
    )
    return read_settings(db)
