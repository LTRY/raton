"""The JSON API under `/api`: one module per subject, assembled here into `router`.

`back/main.py` includes this one router; a new `/api` module adds its router below.
"""

from fastapi import APIRouter, Depends

from back.api import (
    channels,
    curfew,
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
from back.api.errors import error_responses

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
    curfew,
)

# Every `/api` route goes through the couvre-feu guard; it lets through the ones it leaves open.
router = APIRouter(
    dependencies=[Depends(curfew.refuse_during_curfew)], responses=error_responses(423)
)
for module in MODULES:
    router.include_router(module.router)
