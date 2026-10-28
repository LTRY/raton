"""The previews page: HTML, CSS and the status labels of the previews, the deploy and the reviews.

Pure functions of their arguments (the server, ops/server.py, gathers the data), standard
library only. Spec: ops/docs/outil-ops.md, section "Previews des PR".
"""

import html
from urllib.parse import urlsplit

from ops import review as ops_review
from ops.config import CONFIG
from ops.graph import STYLE as GRAPH_STYLE
from ops.graph import render_graph
from ops.jobs import Commit, Job, Preview


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


JOB_BUSY_LABELS = {"up": "Construction…", "down": "Suppression…"}
JOB_ERROR_LABELS = {
    "up": "Échec du déploiement",
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
        return ("", "none")
    if preview.state != "running":
        return (f"Arrêtée ({preview.state})", "error")
    if pr and pr.get("headRefOid") and pr["headRefOid"] != preview.sha:
        return (f"En ligne, en retard ({preview.sha[:7]})", "stale")
    return (f"En ligne ({preview.sha[:7]})", "ok")


STYLE = """
:root { color-scheme: dark; --bg: #0f1115; --card: #181b21; --text: #e8eaf0; --muted: #8b90a0;
  --line: #272b34; --ok: #5cc27a; --busy: #e0a83a; --error: #f07b72; --accent: #6b93ff; --on-accent: #0b1220;
  --col: #13161b; --warn-bg: #2a2114; --warn-line: #8a5a00; --chip: #222b44; }
html, body { overflow-x: clip; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 20px 16px 40px; }
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
button.primary, .open { background: var(--accent); border-color: var(--accent); color: var(--on-accent); font-weight: 600; }
button:disabled { opacity: .5; cursor: default; }
.log { font-size: 13px; color: var(--muted); }
.reviews { margin: 6px 0 0; padding-left: 18px; }
.alert { flex-basis: 100%; }
.alert-head { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; color: var(--busy); }
.alert-head strong { font-size: 15px; }
.alert-count { background: var(--warn-bg); border: 1px solid var(--warn-line); border-radius: 999px; padding: 0 10px;
  font-size: 12px; font-weight: 700; }
.alert p { margin: 4px 0 0; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.board { display: grid; grid-template-columns: repeat(4, minmax(220px, 1fr)); gap: 12px; align-items: start;
  overflow-x: auto; margin-bottom: 18px; padding-bottom: 6px; }
.col { background: var(--col); border: 1px solid var(--line); border-radius: 12px; padding: 10px;
  min-width: 0; min-height: 110px; }
.col.over { outline: 2px dashed var(--accent); outline-offset: -2px; }
.col h2 { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 4px; }
.col .hint { color: var(--muted); font-size: 12px; margin: 0 0 8px; }
.count { font-size: 12px; font-weight: 600; background: var(--chip); border-radius: 999px; padding: 0 8px; }
.card { display: block; margin-bottom: 8px; }
.card[data-pr] { cursor: grab; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
.card.dragging { opacity: .35; }
.ghost { position: fixed; z-index: 10; pointer-events: none; margin: 0; box-shadow: 0 8px 24px rgba(0,0,0,.25);
  transform: rotate(2deg); }
.card .actions { margin-top: 8px; }
.card.done { cursor: default; opacity: .8; }
@media (max-width: 760px) { .board { grid-template-columns: repeat(4, 78vw); } }
footer { margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  color: var(--muted); font-size: 13px; }
"""


DB_LABELS = {"shared": "DB réelle", "copy": "copie de la DB"}


BOARD_COLUMNS = (
    ("draft", "Draft", "Pas prête : déposer ici met la PR en draft."),
    ("todo", "PR à traiter", "Prête pour relecture, sans preview."),
    ("preview", "Preview déployée", "Déposer ici construit la preview (ou la reconstruit)."),
    ("merged", "Merger", "Mergées, pas encore en production. Déposer ici merge la PR (squash)."),
)


def column_of(pr: dict, preview: Preview | None, job: Job | None) -> str:
    """The board column a PR sits in: its draft state, then whether it has a preview."""
    if pr.get("isDraft"):
        return "draft"
    building = job is not None and job.action == "up" and job.returncode is None
    return "preview" if preview is not None or building else "todo"


def render_row(
    host: str | None,
    number: int,
    pr: dict,
    preview: Preview | None,
    job: Job | None,
    column: str | None = None,
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
    status = f'<div class="status {css}">{html.escape(label)}</div>' if label else ""
    card = (
        f'<div class="pr card" data-pr="{number}">'
        if column is not None and not pr.get("isCrossRepository")
        else '<div class="pr">'
    )
    return (
        f'{card}<div class="info"><div class="title">{title}</div>'
        f'<div class="meta">{" · ".join(meta)}{port}</div>'
        f"{status}</div>"
        f'<div class="actions">{"".join(actions)}</div></div>'
    )


def render_merged(pr: dict) -> str:
    title = html.escape(pr.get("title") or "")
    if pr.get("url"):
        title = f'<a href="{html.escape(pr["url"])}">{title}</a>'
    return (
        f'<div class="pr card done"><div class="info"><div class="title">{title}</div>'
        f'<div class="meta">#{pr["number"]} · mergée, pas encore en production</div></div></div>'
    )


# Dragging a card onto a column posts to /prs/<N>/move. Pointer events rather than HTML5 drag and
# drop, which does not work with a finger on a phone: a mouse drags after a few pixels, a finger
# after a long press (a quicker swipe still scrolls the page or the board).
BOARD_SCRIPT = """
(function () {
  var HOLD_MS = 350, SLOP = 8;
  document.querySelectorAll('.card[data-pr]').forEach(function (card) {
    card.addEventListener('pointerdown', function (e) {
      if (e.button || e.target.closest('.actions')) return;
      var x0 = e.clientX, y0 = e.clientY, touch = e.pointerType !== 'mouse';
      var ghost = null, over = null, timer = null, offX = x0 - card.getBoundingClientRect().left;
      var offY = y0 - card.getBoundingClientRect().top;
      function colAt(x, y) { var el = document.elementFromPoint(x, y); return el && el.closest('.col'); }
      function start() {
        ghost = card.cloneNode(true); ghost.classList.add('ghost');
        ghost.style.width = card.offsetWidth + 'px'; document.body.appendChild(ghost);
        card.classList.add('dragging'); move(x0, y0);
      }
      function move(x, y) {
        ghost.style.left = (x - offX) + 'px'; ghost.style.top = (y - offY) + 'px';
        var col = colAt(x, y);
        if (over && over !== col) over.classList.remove('over');
        if (col) col.classList.add('over');
        over = col;
      }
      function onMove(ev) {
        if (!ghost) {
          if (Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) < SLOP) return;
          if (touch) return finish(true);
          start();
        }
        move(ev.clientX, ev.clientY);
      }
      function blockScroll(ev) { if (ghost) ev.preventDefault(); }
      function finish(cancel) {
        clearTimeout(timer);
        document.removeEventListener('pointermove', onMove); document.removeEventListener('pointerup', onUp);
        document.removeEventListener('pointercancel', onCancel); document.removeEventListener('touchmove', blockScroll);
        if (!ghost) return;
        ghost.remove(); card.classList.remove('dragging');
        if (over) over.classList.remove('over');
        if (cancel || !over) return;
        // Dropping a card on its own column does nothing, except in Preview déployée: it rebuilds.
        if (over === card.closest('.col') && over.dataset.col !== 'preview') return;
        if (over.dataset.col === 'merged' && !confirm('Merger la PR ?')) return;
        fetch('/prs/' + card.dataset.pr + '/move', {method: 'POST', body: new URLSearchParams({to: over.dataset.col})})
          .then(function () { location.reload(); });
      }
      function onUp() { finish(false); }
      function onCancel() { finish(true); }
      document.addEventListener('pointermove', onMove); document.addEventListener('pointerup', onUp);
      document.addEventListener('pointercancel', onCancel);
      document.addEventListener('touchmove', blockScroll, {passive: false});
      if (touch) timer = setTimeout(start, HOLD_MS);
      else e.preventDefault();
    });
  });
})();
"""


def render_board(
    host: str | None,
    prs: list[dict],
    previews: dict[int, Preview],
    job_by_pr: dict[int, Job],
    merged: list[dict],
) -> str:
    cards: dict[str, list[str]] = {key: [] for key, _, _ in BOARD_COLUMNS}
    for pr in prs:
        number = pr["number"]
        preview, job = previews.get(number), job_by_pr.get(number)
        column = column_of(pr, preview, job)
        cards[column].append(render_row(host, number, pr, preview, job, column))
    cards["merged"] = [render_merged(pr) for pr in merged]
    columns = "".join(
        f'<section class="col" data-col="{key}"><h2>{html.escape(name)}'
        f'<span class="count">{len(cards[key])}</span></h2>'
        f'<p class="hint">{html.escape(hint)}</p>{"".join(cards[key])}</section>'
        for key, name, hint in BOARD_COLUMNS
    )
    return f'<div class="board">{columns}</div><script>{BOARD_SCRIPT}</script>'


def render_behind_alert(
    version: tuple[str, str],
    pending: list[Commit] | None,
    deployed: str | None,
    behind: int | None,
) -> str:
    """The alert shown when the deployed version trails origin/<branch>: why, and what is missing."""
    if version[1] != "stale":
        return ""
    graph = render_graph(pending, deployed, behind, CONFIG.deploy_branch) if pending else ""
    n = behind or len(pending or [])
    count = f"{n} commit{'s' if n > 1 else ''} de retard" if n else "version différente"
    return (
        '<div class="alert"><div class="alert-head"><strong>⚠ La production est en retard</strong>'
        f'<span class="alert-count">{count}</span></div>'
        f"<p>Ce qui est mergé sur {html.escape(CONFIG.deploy_branch)} n'est pas encore en ligne "
        "tant qu'il n'est pas déployé : utilisez « Déployer main en production ». "
        f"{html.escape(version[0])}</p>{graph}</div>"
    )


def render_prod(
    job: Job | None,
    version: tuple[str, str] | None = None,
    elsewhere: bool = False,
    pending: list[Commit] | None = None,
    deployed: str | None = None,
    behind: int | None = None,
) -> str:
    label, css = prod_status(job, elsewhere)
    version_line = ""
    alert = ""
    if version is not None and version[1] == "stale":
        alert = render_behind_alert(version, pending, deployed, behind)
    elif version is not None:
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
        f"{alert}</div>"
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
    pending_commits: list[Commit] | None = None,
    merged: list[dict] | None = None,
    deployed: str | None = None,
    behind: int | None = None,
) -> str:
    board = render_board(host, prs, previews, job_by_pr, merged or [])
    # A preview whose PR is no longer open still shows, to be removed.
    open_numbers = {pr["number"] for pr in prs}
    rows = [
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
    orphans = f"<h2>Previews de PR fermées</h2>{''.join(rows)}" if rows else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<title>Previews des PR · {html.escape(CONFIG.project_name)}</title><style>{STYLE}{GRAPH_STYLE}</style></head>
<body><main>
<div class="top"><div><h1>Previews des PR</h1>
<p class="lead">Une instance jetable de {html.escape(CONFIG.project_name)} par PR (données de démo), sur le port 9000 + numéro.</p>
</div><a href="/?refresh=1" class="refresh">Rafraîchir</a></div>
{render_prod(prod_job, prod_version, deploy_elsewhere, pending_commits, deployed, behind)}
{review_card}
{banner}{board}{orphans}
<footer><form method="post" action="/sweep"><button>Retirer les previews des PR fermées</button></form>
</footer>
</main></body></html>"""
