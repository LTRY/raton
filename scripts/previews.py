"""The previews page: lists the open PRs and deploys or removes their preview with one click.

`make previews` runs it in its own container (docker-compose.previews.yml); on the host,
`python3 scripts/previews.py [--host 127.0.0.1] [--port 8999]` works too.

A small standard-library server, outside Raton (no import of back/ or front/): it reads the
open PRs with `gh` and runs scripts/preview.sh, which does the work. Each action runs in
the background; its output goes to .local/previews/logs/pr-<N>.log, shown by the page.
Unauthenticated like Raton itself (trusted LAN), but it only ever builds an open PR of this
repository (preview.sh refuses forks), and refuses a form posted from another site.
Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
"""

import argparse
import html
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
PREVIEW_SH = REPO / "scripts" / "preview.sh"
LOG_DIR = REPO / ".local" / "previews" / "logs"


@dataclass
class Preview:
    """A preview container as `preview.sh list` reports it."""

    pr: int
    port: int
    sha: str
    state: str  # docker's container state: running, exited, created...


@dataclass
class Job:
    action: str  # "up" or "down"
    started: float
    returncode: int | None = None


# Running and last finished action of each PR; the page reads it, the action threads write it.
jobs: dict[int, Job] = {}
jobs_lock = threading.Lock()


def parse_previews(text: str) -> dict[int, Preview]:
    previews = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0].isdigit():
            pr = int(parts[0])
            previews[pr] = Preview(pr, int(parts[1]), parts[2], parts[3])
    return previews


def list_previews() -> dict[int, Preview]:
    result = subprocess.run([str(PREVIEW_SH), "list"], capture_output=True, text=True, check=False)
    return parse_previews(result.stdout)


def list_open_prs() -> tuple[list[dict], str | None]:
    """The open PRs, newest first, and the error to show when `gh` cannot list them."""
    fields = "number,title,url,headRefName,headRefOid,isCrossRepository,author"
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", fields],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return [], "La commande gh est introuvable : installez-la et lancez gh auth login."
    if result.returncode != 0:
        return [], f"gh pr list a échoué : {result.stderr.strip()}"
    return sorted(json.loads(result.stdout), key=lambda pr: -pr["number"]), None


def log_path(pr: int) -> Path:
    return LOG_DIR / f"pr-{pr}.log"


def start_job(pr: int, action: str) -> bool:
    """Run `preview.sh <action> <pr>` in the background; False when the PR already has one running."""
    with jobs_lock:
        current = jobs.get(pr)
        if current is not None and current.returncode is None:
            return False
        job = Job(action, time.time())
        jobs[pr] = job

    def run() -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with log_path(pr).open("w") as log:
            process = subprocess.run(
                [str(PREVIEW_SH), action, str(pr)],
                cwd=REPO,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        with jobs_lock:
            job.returncode = process.returncode

    threading.Thread(target=run, daemon=True).start()
    return True


def start_sweep() -> None:
    threading.Thread(
        target=subprocess.run,
        args=([str(PREVIEW_SH), "sweep"],),
        kwargs={"cwd": REPO, "check": False, "capture_output": True},
        daemon=True,
    ).start()


def same_origin(origin: str | None, host: str | None) -> bool:
    """A form posted from another site (a page that targets this LAN address) is refused."""
    if not origin:
        return True
    return urlsplit(origin).netloc == (host or "")


def preview_url(host: str | None, port: int) -> str:
    """The preview on the machine the page was opened on: same hostname, the preview's port."""
    hostname = urlsplit(f"//{host or '127.0.0.1'}").hostname or "127.0.0.1"
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"http://{hostname}:{port}/"


def preview_status(pr: dict, preview: Preview | None, job: Job | None) -> tuple[str, str]:
    """(French label, CSS class) of a PR's preview."""
    if job is not None and job.returncode is None:
        return ("Construction…" if job.action == "up" else "Suppression…", "busy")
    if job is not None and job.returncode != 0:
        return (
            "Échec du déploiement" if job.action == "up" else "Échec de la suppression",
            "error",
        )
    if preview is None:
        return ("Pas de preview", "none")
    if preview.state != "running":
        return (f"Arrêtée ({preview.state})", "error")
    if pr and pr.get("headRefOid") and pr["headRefOid"] != preview.sha:
        return (f"En ligne, en retard ({preview.sha[:7]})", "stale")
    return (f"En ligne ({preview.sha[:7]})", "ok")


STYLE = """
:root { color-scheme: light dark; --bg: #f7f7f5; --card: #fff; --text: #1d1d1f; --muted: #6b6b70;
  --line: #e2e2e0; --ok: #1f7a3a; --busy: #8a5a00; --error: #b3261e; --accent: #2457c5; }
@media (prefers-color-scheme: dark) { :root { --bg: #161618; --card: #1f1f22; --text: #ececee;
  --muted: #9a9aa0; --line: #2e2e33; --ok: #5cc27a; --busy: #e0a83a; --error: #f07b72; --accent: #7aa2ff; } }
html, body { overflow-x: clip; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 820px; margin: 0 auto; padding: 20px 16px 40px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.lead { color: var(--muted); margin: 0 0 18px; }
.banner { border: 1px solid var(--error); color: var(--error); border-radius: 10px; padding: 10px 12px;
  margin-bottom: 14px; overflow-wrap: anywhere; }
.pr { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
.info { flex: 1 1 260px; min-width: 0; }
.title { font-weight: 600; overflow-wrap: anywhere; }
.title a { color: inherit; text-decoration: none; }
.meta { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.status { font-size: 13px; font-weight: 600; }
.ok { color: var(--ok); } .busy { color: var(--busy); } .error, .stale { color: var(--error); }
.none { color: var(--muted); }
.actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
form { margin: 0; }
button, .open { font: inherit; font-size: 14px; border-radius: 8px; padding: 6px 12px; cursor: pointer;
  border: 1px solid var(--line); background: var(--card); color: var(--text); text-decoration: none; }
button.primary, .open { background: var(--accent); border-color: var(--accent); color: #fff; }
button:disabled { opacity: .5; cursor: default; }
.log { font-size: 13px; color: var(--muted); }
footer { margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  color: var(--muted); font-size: 13px; }
"""


def render_row(
    host: str | None, number: int, pr: dict, preview: Preview | None, job: Job | None
) -> str:
    label, css = preview_status(pr, preview, job)
    busy = css == "busy"
    title = html.escape(pr.get("title") or "PR fermée")
    if pr.get("url"):
        title = f'<a href="{html.escape(pr["url"])}">{title}</a>'
    meta = [f"#{number}"]
    if pr.get("headRefName"):
        meta.append(html.escape(pr["headRefName"]))
    if pr.get("author"):
        meta.append(html.escape(pr["author"].get("login", "")))
    actions = []
    if preview is not None and preview.state == "running" and not busy:
        actions.append(
            f'<a class="open" href="{html.escape(preview_url(host, preview.port))}">Ouvrir</a>'
        )
    if pr.get("isCrossRepository"):
        label, css = "Fork : pas de preview", "none"
    elif pr:
        verb = "Redéployer" if preview is not None else "Déployer"
        disabled = " disabled" if busy else ""
        actions.append(
            f'<form method="post" action="/prs/{number}/up">'
            f'<button class="primary"{disabled}>{verb}</button></form>'
        )
    if preview is not None:
        disabled = " disabled" if busy else ""
        actions.append(
            f'<form method="post" action="/prs/{number}/down">'
            f"<button{disabled}>Retirer</button></form>"
        )
    if job is not None:
        actions.append(f'<a class="log" href="/prs/{number}/log">Journal</a>')
    port = f" · port {preview.port}" if preview is not None else ""
    return (
        f'<div class="pr"><div class="info"><div class="title">{title}</div>'
        f'<div class="meta">{" · ".join(meta)}{port}</div>'
        f'<div class="status {css}">{html.escape(label)}</div></div>'
        f'<div class="actions">{"".join(actions)}</div></div>'
    )


def render_page(
    host: str | None,
    prs: list[dict],
    previews: dict[int, Preview],
    job_by_pr: dict[int, Job],
    error: str | None,
) -> str:
    rows = [
        render_row(host, pr["number"], pr, previews.get(pr["number"]), job_by_pr.get(pr["number"]))
        for pr in prs
    ]
    # A preview whose PR is no longer open still shows, to be removed.
    open_numbers = {pr["number"] for pr in prs}
    rows += [
        render_row(host, number, {}, preview, job_by_pr.get(number))
        for number, preview in sorted(previews.items(), reverse=True)
        if number not in open_numbers
    ]
    busy = any(job.returncode is None for job in job_by_pr.values())
    refresh = '<meta http-equiv="refresh" content="4">' if busy else ""
    banner = f'<div class="banner">{html.escape(error)}</div>' if error else ""
    empty = '<p class="lead">Aucune PR ouverte.</p>' if not rows else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<title>Previews des PR · Raton</title><style>{STYLE}</style></head>
<body><main>
<h1>Previews des PR</h1>
<p class="lead">Une instance jetable de Raton par PR (données de démo), sur le port 9000 + numéro.</p>
{banner}{"".join(rows)}{empty}
<footer><form method="post" action="/sweep"><button>Retirer les previews des PR fermées</button></form>
<a href="/" class="log">Rafraîchir</a></footer>
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
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
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts == [""]:
            prs, error = list_open_prs()
            with jobs_lock:
                job_by_pr = dict(jobs)
            page = render_page(self.headers.get("Host"), prs, list_previews(), job_by_pr, error)
            self.send_text(HTTPStatus.OK, page, "text/html")
        elif len(parts) == 3 and parts[0] == "prs" and parts[1].isdigit() and parts[2] == "log":
            path = log_path(int(parts[1]))
            text = path.read_text(errors="replace") if path.exists() else "Aucun journal."
            self.send_text(HTTPStatus.OK, text, "text/plain")
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "Page introuvable.", "text/plain")

    def do_POST(self) -> None:
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
            start_job(int(parts[1]), parts[2])
            self.redirect_home()
        elif parts == ["sweep"]:
            start_sweep()
            self.redirect_home()
        else:
            self.send_text(HTTPStatus.NOT_FOUND, "Action inconnue.", "text/plain")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("PREVIEWS_BIND") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PREVIEWS_PORT") or 8999))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Page des previews sur http://{args.host}:{args.port}/ (Ctrl-C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
