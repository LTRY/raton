"""The front's ASGI app: pages, their no-JS form routes, `/static`, and the `/api` relay.

Run it next to the back: `RATON_API_URL=http://127.0.0.1:8001 uvicorn front.main:app`.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from front import proxy
from front.api import ApiError
from front.compression import TextGZipMiddleware
from front.config import FRONT_DIR, trusted_origins
from front.routes import ROUTERS
from front.same_origin import SameOriginMiddleware
from front.templating import templates

# No OpenAPI schema here: the API and its `/docs` are the back's.
app = FastAPI(title="Raton", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TextGZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(SameOriginMiddleware, trusted_hosts=trusted_origins())


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> HTMLResponse | JSONResponse:
    """A page whose data the back refuses (unknown fiche...) answers like the back did; during the
    couvre-feu (423) it shows the couvre-feu page instead, with the back's message."""
    if exc.status == 423:
        return templates.TemplateResponse(
            request, "curfew.html", {"curfew_mode": True, "detail": exc.detail}, status_code=423
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


app.include_router(proxy.router)
app.mount("/static", StaticFiles(directory=FRONT_DIR / "static"), name="static")
for router in ROUTERS:
    app.include_router(router)
