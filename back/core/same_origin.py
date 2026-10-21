"""Refuse cross-site writes (CSRF).

The app has no login, so a page opened in the same browser could post a form to it ("delete this video")
and the request would be accepted. Browsers label every request: a write whose `Sec-Fetch-Site` is not
`same-origin`, or whose `Origin` (else `Referer`) host differs from the `Host` the request was sent to,
comes from another site and is answered with 403. Requests without any of those headers (curl, scripts)
are not browser-driven and pass. Behind a reverse proxy that rewrites `Host`, list the public host in
`APP_TRUSTED_ORIGINS`.
"""

from urllib.parse import urlparse

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SAME_ORIGIN_FETCH_SITES = {"same-origin", "none"}


class SameOriginMiddleware:
    def __init__(self, app: ASGIApp, trusted_hosts: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.trusted_hosts = frozenset(host.lower() for host in trusted_hosts)

    def _allowed(self, headers: Headers) -> bool:
        fetch_site = headers.get("sec-fetch-site")
        if fetch_site is not None and fetch_site not in SAME_ORIGIN_FETCH_SITES:
            return False
        source = headers.get("origin") or headers.get("referer")
        if source is None:
            return True
        source_host = urlparse(source).netloc.lower()
        if not source_host:
            return False  # `Origin: null` (sandboxed frame, redirect from another site)
        return source_host == headers.get("host", "").lower() or source_host in self.trusted_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            if not self._allowed(Headers(scope=scope)):
                await PlainTextResponse("Requête inter-sites refusée.", status_code=403)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)
