"""The JSON API under `/api`: one module per subject, assembled here into `router`.

`back/main.py` includes this one router; a new `/api` module adds its router below.
"""

from fastapi import APIRouter

from back.api import (
    channels,
    dashboard,
    imports,
    jobs,
    library,
    llm,
    media,
    playlists,
    raton,
    scan,
    settings,
    stats,
    videos,
)

MODULES = (
    channels,
    imports,
    videos,
    library,
    playlists,
    llm,
    jobs,
    scan,
    stats,
    settings,
    raton,
    media,
    dashboard,
)

router = APIRouter()
for module in MODULES:
    router.include_router(module.router)
