from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.common.settings import get_global_quota_bytes
from app.services.llm.usage import llm_spend_by_month
from app.services.videos.charts import library_chart_data, monthly_view, purged_media_by_month
from app.web.shared import templates

router = APIRouter()


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, db: Session = Depends(get_db)):
    data = library_chart_data(db)
    quota_bytes = get_global_quota_bytes(db)
    used_bytes = data["total_bytes"]
    kinds = data["storage_by_kind"]
    for kind in kinds:
        kind["percent"] = round(kind["bytes"] / used_bytes * 100, 1) if used_bytes else 0
    formats = data["cards_by_format"]
    for item in formats:
        item["percent"] = (
            round(item["count"] / data["total_cards"] * 100, 1) if data["total_cards"] else 0
        )
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            **data,
            "chart": monthly_view(data["monthly"]),
            "purged": purged_media_by_month(db),
            "spend": llm_spend_by_month(db),
            "quota_bytes": quota_bytes,
            "quota_percent": round(min(used_bytes / quota_bytes * 100, 100), 1)
            if quota_bytes > 0
            else 0,
        },
    )
