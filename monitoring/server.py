"""The monitoring page: the daily log review of the project, shown and run from one page.

Every project-specific name (skill, tools, hour...) comes from monitoring.toml
(monitoring/config.py).

Usage: python3 -m monitoring.server [--host 127.0.0.1] [--port 8998]
The project starts it as a container (the `monitoring` image stage). The daily review is
scheduled by the process itself (monitoring/review.py).

A small standard-library server that knows nothing of the project it watches. Unauthenticated by
default, like the projects it serves (trusted LAN); with MONITORING_TOKEN set, every request must
carry it as the password of HTTP Basic auth, and a form posted from another site is refused.
Spec: monitoring/docs/outil-monitoring.md.
"""

import argparse
import hmac
import os
from base64 import b64decode
from binascii import Error as Base64Error
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from monitoring import render as monitoring_render
from monitoring import review as monitoring_review


def authorized(header: str | None, token: str) -> bool:
    """True when no token is required, or the Basic auth header carries it as the password."""
    if not token:
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        credentials = b64decode(header[6:], validate=True).decode()
    except Base64Error, UnicodeDecodeError:
        return False
    return hmac.compare_digest(credentials.partition(":")[2].encode(), token.encode())


def same_origin(origin: str | None, host: str | None) -> bool:
    """A form posted from another site (a page that targets this LAN address) is refused."""
    if not origin:
        return True
    return urlsplit(origin).netloc == (host or "")


class Handler(BaseHTTPRequestHandler):
    def deny_unless_authorized(self) -> bool:
        """Answer 401 and return True when the request lacks the MONITORING_TOKEN password."""
        if authorized(self.headers.get("Authorization"), os.environ.get("MONITORING_TOKEN", "")):
            return False
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="monitoring", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def send_text(self, status: HTTPStatus, body: str, content_type: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def redirect_home(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.deny_unless_authorized():
            return
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts == [""]:
            page = monitoring_render.render_page(
                monitoring_review.list_reviews(limit=60),
                monitoring_review.running_since is not None,
            )
            self.send_text(HTTPStatus.OK, page, "text/html")
        elif len(parts) == 2 and parts[0] == "reviews":
            review = monitoring_review.read_review(parts[1])
            if review is None:
                self.send_text(HTTPStatus.NOT_FOUND, "Revue introuvable.", "text/plain")
            else:
                self.send_text(HTTPStatus.OK, review.text, "text/plain")
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "Page introuvable.", "text/plain")

    def do_POST(self) -> None:
        if self.deny_unless_authorized():
            return
        if not same_origin(self.headers.get("Origin"), self.headers.get("Host")):
            self.send_text(HTTPStatus.FORBIDDEN, "Origine refusée.", "text/plain")
            return
        if self.path.strip("/").split("/") == ["reviews", "run"]:
            monitoring_review.start_review(monitoring_review.CONFIG.review_hours, "manual")
            self.redirect_home()
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "Action inconnue.", "text/plain")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("MONITORING_BIND") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MONITORING_PORT") or 8998))
    args = parser.parse_args()
    monitoring_review.start_scheduler()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Page de monitoring sur http://{args.host}:{args.port}/ (Ctrl-C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
