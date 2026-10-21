"""The front's only way to the data: HTTP calls to the back's `/api`.

A refused call raises `ApiError` with the back's own French message (`detail`), which the
routes turn into a redirect with a message, or into the same error status.
"""

from typing import Any

import httpx

from front.config import api_url

TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Api:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def request(self, method: str, path: str, **kwargs) -> Any:
        response = self.client.request(method, f"/api{path}", **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise ApiError(response.status_code, str(detail or f"HTTP {response.status_code}"))
        if response.status_code == 204 or not response.content:
            return None
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response

    def get(self, path: str, **params) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, json: Any = None, **kwargs) -> Any:
        return self.request("POST", path, json=json, **kwargs)

    def put(self, path: str, json: Any = None) -> Any:
        return self.request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


_api: Api | None = None


def get_api() -> Api:
    """FastAPI dependency; tests override it with an `Api` wired to the back in-process."""
    global _api
    if _api is None:
        _api = Api(httpx.Client(base_url=api_url(), timeout=TIMEOUT))
    return _api
