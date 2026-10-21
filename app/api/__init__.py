"""The JSON API under `/api`: one module per subject, assembled here into `router`.

`app/main.py` includes this one router; a new `/api` module adds its router below.
"""

from fastapi import APIRouter

from app.api import channels, jobs, library, llm, playlists, settings, stats, videos

MODULES = (channels, videos, library, playlists, llm, jobs, stats, settings)

router = APIRouter()
for module in MODULES:
    router.include_router(module.router)
