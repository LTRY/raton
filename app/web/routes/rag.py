from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.rag_dashboard import rag_dashboard_data
from app.web.shared import templates

router = APIRouter()


@router.get("/rag", response_class=HTMLResponse)
def rag_dashboard_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "rag_dashboard.html", rag_dashboard_data(db))
