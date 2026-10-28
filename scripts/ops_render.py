"""The previews page: HTML, CSS and the status labels of the previews, the deploy and the reviews.

Pure functions of their arguments (the server, scripts/previews.py, gathers the data), standard
library only. Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
"""

import html
from urllib.parse import urlsplit

from scripts import ops_review
from scripts.ops_config import CONFIG
from scripts.ops_jobs import Job, Preview


def preview_url(host: str | None, port: int) -> str:
    """The preview on the machine the page was opened on: same hostname, the preview's port."""
    hostname = urlsplit(f"//{host or '127.0.0.1'}").hostname or "127.0.0.1"
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"http://{hostname}:{port}/"


def prod_status(job: Job | None, elsewhere: bool = False) -> tuple[str, str]:
    """(French label, CSS class) of the last production deploy launched from this page.

    `elsewhere`: a deploy that this page did not start holds the deploy lock.
    """
    if job is not None and job.returncode is None:
        return ("Déploiement en cours…", "busy")
    if elsewhere:
        return ("Déploiement déjà en cours (lancé hors de cette page)", "busy")
    if job is None:
        return ("Aucun déploiement lancé depuis cette page", "none")
    if job.interrupted:
        return ("Déploiement interrompu (la page a redémarré)", "error")
    if job.returncode != 0:
        return ("Échec du déploiement", "error")
    return ("Déployée", "ok")


def version_status(deployed: str | None, origin: str | None, behind: int | None) -> tuple[str, str]:
    """(French label, CSS class) comparing the deployed main with origin/main."""
    if deployed is None:
        return ("Version déployée inconnue (visible après le prochain make up)", "none")
    if origin is None:
        return (f"Déployée : {deployed[:7]} (origin/main injoignable)", "none")
    if deployed == origin:
        return (f"À jour avec origin/main ({deployed[:7]})", "ok")
    if behind:
        plural = "s" if behind > 1 else ""
        return (
            f"En retard de {behind} commit{plural} : {deployed[:7]} déployé, origin/main {origin[:7]}",
            "stale",
        )
    return (f"Différente d'origin/main : {deployed[:7]} déployé, origin/main {origin[:7]}", "stale")


JOB_BUSY_LABELS = {"up": "Construction…", "rebase": "Rebase…", "down": "Suppression…"}
JOB_ERROR_LABELS = {
    "up": "Échec du déploiement",
    "rebase": "Échec du rebase",
    "down": "Échec de la suppression",
}


def preview_status(pr: dict, preview: Preview | None, job: Job | None) -> tuple[str, str]:
    """(French label, CSS class) of a PR's preview."""
    if job is not None and job.returncode is None:
        return (JOB_BUSY_LABELS[job.action], "busy")
    if job is not None and job.interrupted:
        return ("Interrompu (la page a redémarré)", "error")
    if job is not None and job.returncode != 0:
        return (JOB_ERROR_LABELS[job.action], "error")
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
.top { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: flex-start;
  justify-content: space-between; }
.top > div { min-width: 0; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 0; }
.lead { color: var(--muted); margin: 0 0 18px; }
.banner { border: 1px solid var(--error); color: var(--error); border-radius: 10px; padding: 10px 12px;
  margin-bottom: 14px; overflow-wrap: anywhere; }
.pr { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
.prod { border-color: var(--accent); margin-bottom: 22px; }
.info { flex: 1 1 260px; min-width: 0; }
.title { font-weight: 600; overflow-wrap: anywhere; }
.title a { color: inherit; text-decoration: none; }
.meta { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.status { font-size: 13px; font-weight: 600; }
.ok { color: var(--ok); } .busy { color: var(--busy); } .error, .stale { color: var(--error); }
.none { color: var(--muted); }
.actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
form { margin: 0; }
button, .open, .refresh { font: inherit; font-size: 14px; border-radius: 8px; padding: 6px 12px; cursor: pointer;
  border: 1px solid var(--line); background: var(--card); color: var(--text); text-decoration: none; }
button.primary, .open { background: var(--accent); border-color: var(--accent); color: #fff; }
button:disabled { opacity: .5; cursor: default; }
.log { font-size: 13px; color: var(--muted); }
.reviews { margin: 6px 0 0; padding-left: 18px; }
footer { margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  color: var(--muted); font-size: 13px; }
"""


DB_LABELS = {"shared": "DB réelle", "copy": "copie de la DB"}


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
    if pr and not pr.get("isCrossRepository"):
        disabled = " disabled" if busy else ""
        actions.append(
            f'<form method="post" action="/prs/{number}/rebase">'
            f"<button{disabled}>Rebase</button></form>"
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
    if preview is not None and preview.db in DB_LABELS:
        port += f" · {DB_LABELS[preview.db]}"
    return (
        f'<div class="pr"><div class="info"><div class="title">{title}</div>'
        f'<div class="meta">{" · ".join(meta)}{port}</div>'
        f'<div class="status {css}">{html.escape(label)}</div></div>'
        f'<div class="actions">{"".join(actions)}</div></div>'
    )


def render_prod(
    job: Job | None, version: tuple[str, str] | None = None, elsewhere: bool = False
) -> str:
    label, css = prod_status(job, elsewhere)
    version_line = ""
    if version is not None:
        version_line = f'<div class="status {version[1]}">{html.escape(version[0])}</div>'
    disabled = " disabled" if css == "busy" else ""
    # The real stack and its data: a stray tap must not rebuild it.
    name = CONFIG.project_name.replace("'", "")
    confirm = html.escape(f"return confirm('Déployer main sur la vraie instance de {name} ?')")
    log = '<a class="log" href="/prod/log">Journal</a>' if job is not None else ""
    return (
        '<div class="pr prod"><div class="info"><h2>Production</h2>'
        '<div class="meta">Met le dépôt à jour sur origin/main puis lance make up.</div>'
        f"{version_line}"
        f'<div class="status {css}">{html.escape(label)}</div></div>'
        f'<div class="actions"><form method="post" action="/prod/deploy" onsubmit="{confirm}">'
        f'<button class="primary"{disabled}>Déployer main en production</button></form>{log}</div>'
        "</div>"
    )


def render_page(
    host: str | None,
    prs: list[dict],
    previews: dict[int, Preview],
    job_by_pr: dict[int, Job],
    error: str | None,
    prod_job: Job | None = None,
    reviews: list[ops_review.Review] | None = None,
    review_busy: bool = False,
    prod_version: tuple[str, str] | None = None,
    deploy_elsewhere: bool = False,
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
    busy = (
        any(job.returncode is None for job in job_by_pr.values())
        or (prod_job is not None and prod_job.returncode is None)
        or deploy_elsewhere
        or review_busy
    )
    review_card = "" if reviews is None else ops_review.render_reviews(reviews, review_busy)
    refresh = '<meta http-equiv="refresh" content="4">' if busy else ""
    banner = f'<div class="banner">{html.escape(error)}</div>' if error else ""
    empty = '<p class="lead">Aucune PR ouverte.</p>' if not rows else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<title>Previews des PR · {html.escape(CONFIG.project_name)}</title><style>{STYLE}</style></head>
<body><main>
<div class="top"><div><h1>Previews des PR</h1>
<p class="lead">Une instance jetable de {html.escape(CONFIG.project_name)} par PR (données de démo), sur le port 9000 + numéro.</p>
</div><a href="/" class="refresh">Rafraîchir</a></div>
{render_prod(prod_job, prod_version, deploy_elsewhere)}
{review_card}
{banner}{"".join(rows)}{empty}
<footer><form method="post" action="/sweep"><button>Retirer les previews des PR fermées</button></form>
</footer>
</main></body></html>"""
