"""Settings of the front, read from the environment (the front has no database and no secret)."""

import os
from pathlib import Path

FRONT_DIR = Path(__file__).resolve().parent


def api_url() -> str:
    """Where the back listens; its routes all live under `/api`."""
    return os.environ.get("RATON_API_URL", "http://127.0.0.1:8001").rstrip("/")


def trusted_origins() -> frozenset[str]:
    """Hosts allowed to post forms besides the request's own (behind a reverse proxy)."""
    value = os.environ.get("APP_TRUSTED_ORIGINS", "")
    return frozenset(host.strip() for host in value.split(",") if host.strip())
