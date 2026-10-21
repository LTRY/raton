from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from front.api import Api, get_api
from front.records import record
from front.templating import templates

router = APIRouter()


@router.get("/raton/variations", response_class=HTMLResponse)
def raton_variations_page(request: Request, api: Api = Depends(get_api)):
    """Test page: every line of every scenario, with no condition and no visit bookkeeping."""
    variations = record(api.get("/raton/variations"))
    return templates.TemplateResponse(
        request,
        "raton_variations.html",
        {
            "variations": variations,
            "line_count": sum(len(group.lines) for group in variations),
        },
    )
