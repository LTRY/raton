"""The back's ASGI app: the JSON API under `/api`, its lifespan (scheduler, demo tables).

FastAPI is an ASGI web framework: this module builds one `FastAPI` object (`app`), and an ASGI
server (uvicorn) imports it as `back.main:app` and hands it every incoming HTTP request. The
routes live in `back/api/` (one module per subject, assembled in `back/api/__init__.py`); the
pages are the front's (`front/`), which calls this API like any other client.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from back.api import router as api_router
from back.api.errors import validation_error_handler
from back.core.compression import TextGZipMiddleware
from back.core.config import get_settings
from back.core.logging import configure_app_logging, log_event
from back.core.request_timing import (
    RequestTimingMiddleware,
    event_loop_lag_probe,
    install_sql_timing,
)
from back.core.same_origin import SameOriginMiddleware
from back.db.session import Base, engine, get_db
from back.services.common.settings import ensure_default_settings
from back.services.jobs.scheduler import start_scheduler, stop_scheduler


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
    # The scheduler runs inside this process, not in a separate worker: run one back only.
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
# The browser's writes reach the back through the front's relay, which forwards their Host and
# Origin: the same-origin check still applies to them.
app.add_middleware(
    SameOriginMiddleware,
    trusted_hosts=frozenset(
        h.strip() for h in get_settings().trusted_origins.split(",") if h.strip()
    ),
)
# Added last = outermost: it times the whole stack, gzip included.
app.add_middleware(RequestTimingMiddleware)

app.include_router(api_router)
app.add_exception_handler(RequestValidationError, validation_error_handler)
