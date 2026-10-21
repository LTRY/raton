"""`/api/*` of the browser, relayed to the back: the pages' scripts and the media players call
the same origin as the page, so no CORS and the same-origin check of the back still applies.

The request's own `Host`, `Origin` and `Sec-Fetch-*` headers are forwarded as they came; the
body streams both ways (uploads, `Range` requests on audio and video).
"""

import httpx
from fastapi import APIRouter, Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from front.config import api_url

router = APIRouter()

# Hop-by-hop headers, and the ones the relay recomputes itself.
DROPPED_REQUEST_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "accept-encoding",
    "content-length",
}
DROPPED_RESPONSE_HEADERS = {"connection", "keep-alive", "transfer-encoding", "content-encoding"}

_client: httpx.AsyncClient | None = None


def proxy_client() -> httpx.AsyncClient:
    """The client the relay uses; tests replace it with one bound to the back in-process."""
    global _client
    if _client is None:
        # No read timeout: a video stream stays open as long as it plays.
        _client = httpx.AsyncClient(base_url=api_url(), timeout=httpx.Timeout(None, connect=5.0))
    return _client


@router.api_route("/api/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
async def relay(request: Request, path: str) -> StreamingResponse:
    headers = [
        (name, value)
        for name, value in request.headers.items()
        if name.lower() not in DROPPED_REQUEST_HEADERS
    ]
    # The front compresses what it sends back; the back answers in clear.
    headers.append(("accept-encoding", "identity"))
    if request.client:
        headers.append(("x-forwarded-for", request.client.host))
    client = proxy_client()
    upstream = await client.send(
        client.build_request(
            request.method,
            f"/api/{path}" + (f"?{request.url.query}" if request.url.query else ""),
            headers=headers,
            content=request.stream(),
        ),
        stream=True,
    )
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers={
            name: value
            for name, value in upstream.headers.items()
            if name.lower() not in DROPPED_RESPONSE_HEADERS
        },
        background=BackgroundTask(upstream.aclose),
    )
