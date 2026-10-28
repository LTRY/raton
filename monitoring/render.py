"""The monitoring page: HTML and CSS around the cards of the monitoring tool.

Pure functions of their arguments (the server, monitoring/server.py, gathers the data), standard
library only. Spec: monitoring/docs/outil-monitoring.md, section "Page de monitoring".
"""

import html

from monitoring import review as monitoring_review
from monitoring.config import CONFIG

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
.pr { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
.prod { border-color: var(--accent); margin-bottom: 22px; }
.info { flex: 1 1 260px; min-width: 0; }
.meta { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.status { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.ok { color: var(--ok); } .busy { color: var(--busy); } .error { color: var(--error); }
.none { color: var(--muted); }
.actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
form { margin: 0; }
button, .refresh { font: inherit; font-size: 14px; border-radius: 8px; padding: 6px 12px; cursor: pointer;
  border: 1px solid var(--line); background: var(--card); color: var(--text); text-decoration: none; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button:disabled { opacity: .5; cursor: default; }
.reviews { margin: 6px 0 0; padding-left: 18px; }
"""


def render_page(reviews: list[monitoring_review.Review], review_busy: bool) -> str:
    refresh = '<meta http-equiv="refresh" content="4">' if review_busy else ""
    name = html.escape(CONFIG.project_name)
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<title>Monitoring · {name}</title><style>{STYLE}</style></head>
<body><main>
<div class="top"><div><h1>Monitoring</h1>
<p class="lead">Surveillance de {name}.</p>
</div><a href="/" class="refresh">Rafraîchir</a></div>
{monitoring_review.render_reviews(reviews, review_busy)}
</main></body></html>"""
