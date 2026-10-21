from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.llm.usage import llm_spend_by_month
from app.services.videos.charts import library_stats, monthly_view
from app.web.shared import templates

router = APIRouter()


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, db: Session = Depends(get_db)):
    stats = library_stats(db)
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            **stats,
            "chart": monthly_view(stats["monthly"]),
            "spend": llm_spend_by_month(db),
        },
    )
