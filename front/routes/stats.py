from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from front.api import Api, get_api
from front.charts import monthly_view
from front.records import record
from front.templating import templates

router = APIRouter()


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, api: Api = Depends(get_api)):
    charts = api.get("/stats/charts")
    return templates.TemplateResponse(
        request,
        "stats.html",
        {**vars(record(charts)), "chart": monthly_view(charts["monthly"])},
    )


@router.get("/rag", response_class=HTMLResponse)
def rag_dashboard_page(request: Request, api: Api = Depends(get_api)):
    return templates.TemplateResponse(request, "rag_dashboard.html", vars(record(api.get("/rag"))))
