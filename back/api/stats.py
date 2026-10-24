"""`/api/stats` and `/api/rag`: the data of the `/stats` and `/rag` pages."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from back.api.users import current_user_id
from back.db.session import get_db
from back.schemas.stats import (
    AutoNotesRunRead,
    LibraryCountsRead,
    RagDashboardRead,
    StatsChartsRead,
)
from back.services.common.settings import get_setting
from back.services.llm.usage import llm_spend_by_month
from back.services.rag.auto_notes import LAST_RUN_AT_KEY as AUTO_NOTES_LAST_RUN_AT_KEY
from back.services.rag.auto_notes import LAST_RUN_SUMMARY_KEY as AUTO_NOTES_LAST_RUN_SUMMARY_KEY
from back.services.rag.dashboard import rag_dashboard_data
from back.services.videos.charts import library_stats
from back.services.videos.stats import library_counts

router = APIRouter(prefix="/api", tags=["Statistiques"])


@router.get("/stats", response_model=LibraryCountsRead)
def get_stats(
    db: Session = Depends(get_db), user_id: int = Depends(current_user_id)
) -> LibraryCountsRead:
    counts = library_counts(db, user_id)
    return LibraryCountsRead(
        channels=counts["channel_count"],
        rated_channels=counts["rated_channel_count"],
        videos=counts["video_count"],
        regular_videos=counts["regular_video_count"],
        shorts=counts["short_count"],
        downloaded_media=counts["downloaded_media_count"],
        transcripts=counts["transcript_count"],
        used_bytes=counts["used_bytes"],
        quota_bytes=counts["quota_bytes"],
        storage_percent=counts["storage_percent"],
    )


@router.get("/stats/charts", response_model=StatsChartsRead)
def get_stats_charts(db: Session = Depends(get_db)) -> dict:
    """What `/stats` shows, with the full 12-month `monthly` window (the page draws a trimmed one)."""
    return {**library_stats(db), "spend": llm_spend_by_month(db)}


@router.get("/rag", response_model=RagDashboardRead)
def get_rag_dashboard(db: Session = Depends(get_db)) -> dict:
    """What `/rag` shows about the notes indexing."""
    return rag_dashboard_data(db)


@router.get("/auto-notes", response_model=AutoNotesRunRead)
def get_auto_notes_run(db: Session = Depends(get_db)) -> AutoNotesRunRead:
    last_run_at = get_setting(db, AUTO_NOTES_LAST_RUN_AT_KEY, "")
    return AutoNotesRunRead(
        last_run_at=datetime.fromisoformat(last_run_at) if last_run_at else None,
        last_run_summary=get_setting(db, AUTO_NOTES_LAST_RUN_SUMMARY_KEY, ""),
    )
