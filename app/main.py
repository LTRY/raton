"""FastAPI application composition: lifespan, routers, static files.

FastAPI is an ASGI web framework: this module builds one `FastAPI` object
(`app`), and an ASGI server (uvicorn) imports it as `app.main:app` and hands it
every incoming HTTP request. FastAPI matches the request path against the
registered routes and calls the matching Python function.

Routes are not declared here. Each feature area defines an `APIRouter` (a group
of routes) in its own module, and this file only plugs those routers into the
app with `include_router`. Keep it that way: a route goes in the matching
`app/web/routes/` module, a helper in `app/web/` or `app/services/`.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.core.logging import configure_app_logging, log_event
from app.db.session import Base, engine, get_db
from app.services.common.settings import ensure_default_settings
from app.services.jobs.scheduler import start_scheduler, stop_scheduler
from app.web.compression import TextGZipMiddleware
from app.web.request_timing import RequestTimingMiddleware, event_loop_lag_probe, install_sql_timing
from app.web.routes.channels import router as channels_router
from app.web.routes.dashboard import router as dashboard_router
from app.web.routes.library_chat import router as library_chat_router
from app.web.routes.media import router as media_router
from app.web.routes.playlists import router as playlists_router
from app.web.routes.rag import router as rag_router
from app.web.routes.raton import router as raton_router
from app.web.routes.settings import router as settings_router
from app.web.routes.stats import router as stats_router
from app.web.routes.transcript import router as transcript_router
from app.web.routes.videos import router as videos_router
from app.web.same_origin import SameOriginMiddleware


# The lifespan is FastAPI's startup/shutdown hook. It is an async context
# manager that FastAPI enters once when the server starts and exits once when
# it stops:
#   - code before `yield` runs at startup, before the first request is served;
#   - while the function is paused on `yield`, the app serves requests;
#   - code after `yield` runs at shutdown, once the server stops accepting requests.
# It runs once per server process, not once per request.
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_app_logging(get_settings().log_dir)
    log_event(logging.getLogger("raton.app"), "app.started")
    # Direct table creation is only for demo mode (sqlite, `make demo`);
    # everywhere else the schema is managed by Alembic migrations.
    if get_settings().auto_create_tables:
        Base.metadata.create_all(bind=engine)
    # `get_db` is a generator meant for FastAPI's per-request dependency
    # injection. There is no request here, so we pull one session out of it by
    # hand and close it ourselves.
    db = next(get_db())
    try:
        ensure_default_settings(db)
    finally:
        db.close()
    # The scheduler runs inside this web process, not in a separate worker.
    start_scheduler()
    install_sql_timing(engine)
    lag_probe = asyncio.create_task(event_loop_lag_probe())
    yield
    lag_probe.cancel()
    stop_scheduler()
    log_event(logging.getLogger("raton.app"), "app.stopping")


# The application object. Passing `lifespan` is what registers the hook above.
app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.add_middleware(TextGZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(
    SameOriginMiddleware,
    trusted_hosts=frozenset(
        h.strip() for h in get_settings().trusted_origins.split(",") if h.strip()
    ),
)
# Added last = outermost: it times the whole stack, gzip included.
app.add_middleware(RequestTimingMiddleware)

# `include_router` copies a router's routes into the app. Routes are matched in
# registration order and the first match wins, so the order below is the route
# resolution order: do not reorder without checking that no path shadows another.
app.include_router(api_router)
app.include_router(media_router)
app.include_router(settings_router)
app.include_router(stats_router)
app.include_router(rag_router)
app.include_router(playlists_router)
# `mount` attaches a separate sub-application at a path prefix: everything under
# /static is served straight from disk.
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(dashboard_router)
app.include_router(raton_router)
app.include_router(channels_router)
app.include_router(videos_router)
app.include_router(transcript_router)
app.include_router(library_chat_router)
