"""The MCP server's only way to the data: HTTP calls to the back's `/api`."""

import os
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(60.0, connect=5.0)


def api_url() -> str:
    """Where the back listens; its routes all live under `/api`."""
    return os.environ.get("RATON_API_URL", "http://127.0.0.1:8001").rstrip("/")


class ApiError(ValueError):
    """A call the back refused; the message is its own French `detail`, shown to the client."""


_client: httpx.Client | None = None


def get(path: str, **params: Any) -> Any:
    """GET `/api{path}` and return the decoded JSON; `None` parameters are left out."""
    global _client
    if _client is None:
        _client = httpx.Client(base_url=api_url(), timeout=TIMEOUT)
    response = _client.get(
        f"/api{path}", params={key: value for key, value in params.items() if value is not None}
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        raise ApiError(str(detail or f"HTTP {response.status_code}"))
    return response.json()
