"""`/api/stats` and `/api/rag`: the data of the `/stats` and `/rag` pages."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.stats import LibraryCountsRead, RagDashboardRead, StatsChartsRead
from app.services.llm.usage import llm_spend_by_month
from app.services.rag.dashboard import rag_dashboard_data
from app.services.videos.charts import library_stats
from app.services.videos.stats import library_counts

router = APIRouter(prefix="/api", tags=["Statistiques"])


@router.get("/stats", response_model=LibraryCountsRead)
def get_stats(db: Session = Depends(get_db)) -> LibraryCountsRead:
    counts = library_counts(db)
    return LibraryCountsRead(
        channels=counts["channel_count"],
        videos=counts["video_count"],
        used_bytes=counts["used_bytes"],
        quota_bytes=counts["quota_bytes"],
    )


@router.get("/stats/charts", response_model=StatsChartsRead)
def get_stats_charts(db: Session = Depends(get_db)) -> dict:
    """What `/stats` shows, with the full 12-month `monthly` window (the page draws a trimmed one)."""
    return {**library_stats(db), "spend": llm_spend_by_month(db)}


@router.get("/rag", response_model=RagDashboardRead)
def get_rag_dashboard(db: Session = Depends(get_db)) -> dict:
    """What `/rag` shows about the notes indexing."""
    return rag_dashboard_data(db)
