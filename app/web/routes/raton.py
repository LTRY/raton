from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services.raton.picker import all_variations
from app.web.shared import templates

router = APIRouter()


@router.get("/raton/variations", response_class=HTMLResponse)
def raton_variations_page(request: Request):
    """Test page: every line of every scenario, with no condition and no visit bookkeeping."""
    variations = all_variations()
    return templates.TemplateResponse(
        request,
        "raton_variations.html",
        {
            "variations": variations,
            "line_count": sum(len(group["lines"]) for group in variations),
        },
    )
