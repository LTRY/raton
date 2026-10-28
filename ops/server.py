"""The previews page: lists the open PRs and deploys or removes their preview with one click.

It also deploys main to the real stack (button at the top of the page). Every project-specific
name (scripts, container, image label...) comes from ops.toml (ops/config.py).

Usage: python3 -m ops.server [--host 127.0.0.1] [--port 8999] [--scheduler]
The project starts it as a container (the `ops` image stage), with --scheduler:
the daily log review (ops/review.py).

A small standard-library server that knows nothing of the project it serves: it reads the
open PRs with `gh` and runs the project's preview and deploy scripts (ops/jobs.py), and
renders the page with ops/render.py. Each action runs in the background; its output goes
to .local/previews/logs/ (pr-<N>.log, prod.log), shown by the page; their state is kept in
.local/previews/jobs/ so a restart of the page does not forget them.
Unauthenticated by default, like the projects it serves (trusted LAN); with OPS_TOKEN set, every request must
carry it as the password of HTTP Basic auth. It only ever builds an open PR of this repository
(preview.sh refuses forks), and refuses a form posted from another site.
Spec: ops/docs/outil-ops.md.
"""

import argparse
import hmac
import os
from base64 import b64decode
from binascii import Error as Base64Error
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from ops import jobs as ops_jobs
from ops import render as ops_render
from ops import review as ops_review

# Whether this process runs the daily log review (--scheduler); set by main().
SCHEDULER_ON = False


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
        """Answer 401 and return True when the request lacks the OPS_TOKEN password."""
        if authorized(self.headers.get("Authorization"), os.environ.get("OPS_TOKEN", "")):
            return False
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="ops", charset="UTF-8"')
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
            if "refresh=1" in self.path.partition("?")[2].split("&"):
                ops_jobs.invalidate_caches()
            prs, error = ops_jobs.list_open_prs()
            with ops_jobs.jobs_lock:
                job_by_pr = dict(ops_jobs.jobs)
                prod = ops_jobs.prod_job
            deployed, origin = ops_jobs.deployed_sha(), ops_jobs.origin_main_sha()
            behind = ops_jobs.commits_behind(deployed, origin) if deployed and origin else None
            pending = ops_jobs.pending_commits(deployed, origin) if behind else []
            previews, preview_warning = ops_jobs.list_previews()
            flash, ops_jobs.flash_error = ops_jobs.flash_error, None
            page = ops_render.render_page(
                self.headers.get("Host"),
                prs,
                previews,
                job_by_pr,
                " ".join(filter(None, (error, preview_warning, flash))) or None,
                prod,
                ops_review.list_reviews(limit=60) if SCHEDULER_ON else None,
                ops_review.running_since is not None,
                ops_render.version_status(deployed, origin, behind),
                ops_jobs.deploy_elsewhere(prod),
                pending,
                ops_jobs.list_merged_prs(),
            )
            self.send_text(HTTPStatus.OK, page, "text/html")
        elif len(parts) == 3 and parts[0] == "prs" and parts[1].isdigit() and parts[2] == "log":
            path = ops_jobs.log_path(int(parts[1]))
            text = path.read_text(errors="replace") if path.exists() else "Aucun journal."
            self.send_text(HTTPStatus.OK, text, "text/plain")
        elif len(parts) == 2 and parts[0] == "reviews":
            review = ops_review.read_review(parts[1])
            if review is None:
                self.send_text(HTTPStatus.NOT_FOUND, "Revue introuvable.", "text/plain")
            else:
                self.send_text(HTTPStatus.OK, review.text, "text/plain")
        elif parts == ["prod", "log"]:
            prod_log = ops_jobs.PROD_LOG
            text = prod_log.read_text(errors="replace") if prod_log.exists() else "Aucun journal."
            self.send_text(HTTPStatus.OK, text, "text/plain")
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "Page introuvable.", "text/plain")

    def do_POST(self) -> None:
        if self.deny_unless_authorized():
            return
        if not same_origin(self.headers.get("Origin"), self.headers.get("Host")):
            self.send_text(HTTPStatus.FORBIDDEN, "Origine refusée.", "text/plain")
            return
        parts = self.path.strip("/").split("/")
        if (
            len(parts) == 3
            and parts[0] == "prs"
            and parts[1].isdigit()
            and parts[2] in ("up", "down")
        ):
            ops_jobs.start_job(int(parts[1]), parts[2])
            self.redirect_home()
        elif len(parts) == 3 and parts[0] == "prs" and parts[1].isdigit() and parts[2] == "move":
            length = int(self.headers.get("Content-Length") or 0)
            fields = parse_qs(self.rfile.read(min(length, 1024)).decode(errors="replace"))
            ops_jobs.flash_error = ops_jobs.move_pr(int(parts[1]), fields.get("to", [""])[0])
            self.redirect_home()
        elif parts == ["prod", "deploy"]:
            ops_jobs.start_prod_deploy()
            self.redirect_home()
        elif parts == ["reviews", "run"] and SCHEDULER_ON:
            ops_review.start_review(ops_review.CONFIG.review_hours, "manual")
            self.redirect_home()
        elif parts == ["sweep"]:
            ops_jobs.start_sweep()
            self.redirect_home()
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "Action inconnue.", "text/plain")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("PREVIEWS_BIND") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PREVIEWS_PORT") or 8999))
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="run the daily log review (ops/review.py) and show it on the page",
    )
    args = parser.parse_args()
    ops_jobs.load_jobs()
    if args.scheduler:
        global SCHEDULER_ON
        SCHEDULER_ON = True
        ops_review.start_scheduler()
    if not os.environ.get("OPS_TOKEN") and args.host not in ("127.0.0.1", "localhost", "::1"):
        print("OPS_TOKEN est vide : la page, qui déploie, est ouverte à tout le réseau.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Page des previews sur http://{args.host}:{args.port}/ (Ctrl-C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
