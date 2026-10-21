"""Gzip for the text responses of the app (HTML, CSS, JS, JSON), and only those.

Starlette's `GZipMiddleware` compresses every response it is not told to skip. Here that would also
gzip audio/video and image streams: no gain on already-compressed data, wasted CPU, and a changed
`Content-Length` under `Range` requests. This subclass decides on the response's content type.
"""

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder
from starlette.types import Message, Receive, Scope, Send

COMPRESSIBLE_CONTENT_TYPES = (
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/json",
    "image/svg+xml",
)


class TextOnlyGZipResponder(GZipResponder):
    async def send_with_compression(self, message: Message) -> None:
        await super().send_with_compression(message)
        if message["type"] == "http.response.start":
            content_type = Headers(raw=message["headers"]).get("content-type", "")
            if not content_type.startswith(COMPRESSIBLE_CONTENT_TYPES):
                # Read by the parent for every following body message of this response.
                self.content_type_is_excluded = True


class TextGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get("Accept-Encoding", ""):
            await TextOnlyGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
