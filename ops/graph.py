"""The commit graph of the production alert: what origin/<branch> has that the deployed version lacks.

Pure functions of their arguments, standard library only, drawn like a git client's history:
a vertical line, one dot per commit coloured by author, the branch on top and the deployed
commit at the bottom. Spec: docs/spec (the project's), section "Previews des PR".
"""

import html
import re
import time

from ops.jobs import Commit

# Leading [TAG] groups and a trailing (#N) of a commit title become chips.
TITLE_TAGS = re.compile(r"((?:\[[A-Za-z]+\])+)\s*(.*?)(?:\s*\(#(\d+)\))?")

STYLE = """
.graph { position: relative; margin-top: 4px; padding-left: 0; }
.graph::before { content: ""; position: absolute; left: 11px; top: 14px; bottom: 14px; width: 2px;
  background: linear-gradient(var(--accent), var(--line)); border-radius: 2px; }
.g-row { position: relative; display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 0 8px;
  align-items: center; padding: 4px 0; }
.g-dot { justify-self: center; width: 12px; height: 12px; box-sizing: border-box; border-radius: 50%;
  background: var(--card); border: 3px solid var(--c, var(--accent)); z-index: 1; }
.g-dot.end { width: 16px; height: 16px; background: var(--c, var(--accent)); }
.g-card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 7px 10px;
  min-width: 0; }
.g-title { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: baseline; }
.ctitle { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.g-meta { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; margin-top: 4px;
  color: var(--muted); font-size: 12px; }
.sha { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--chip); color: var(--accent);
  border-radius: 6px; padding: 1px 6px; }
.tag { font-size: 11px; font-weight: 700; letter-spacing: .03em; background: var(--accent); color: #fff;
  border-radius: 999px; padding: 1px 8px; }
.pr-ref { color: var(--muted); font-size: 12px; }
.avatar { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%;
  background: var(--c); color: #fff; font-size: 10px; font-weight: 700; }
.branch { font-weight: 700; font-size: 13px; border-radius: 999px; padding: 2px 10px; color: #fff;
  background: var(--accent); }
.branch.prod { background: var(--ok); }
.g-more { color: var(--muted); font-size: 12px; }
"""


def author_color(author: str) -> str:
    """A stable colour per author, so the same person keeps the same dot."""
    return f"hsl({sum(map(ord, author)) * 37 % 360} 62% 48%)"


def ago(timestamp: int, now: float) -> str:
    """French relative age: « il y a 3 h »."""
    seconds = max(0, int(now - timestamp))
    if seconds < 60:
        return "à l'instant"
    for limit, unit, size in ((3600, "min", 60), (86400, "h", 3600), (30 * 86400, "j", 86400)):
        if seconds < limit:
            return f"il y a {seconds // size} {unit}"
    return f"il y a {seconds // (30 * 86400)} mois"


def render_commit(commit: Commit, now: float) -> str:
    """One row of the graph: dot, [TAG] chips, title, (#N) reference, sha, author and age."""
    match = TITLE_TAGS.fullmatch(commit.title)
    tags, text, ref = match.groups() if match else ("", commit.title, None)
    chips = "".join(
        f'<span class="tag">{html.escape(tag)}</span>' for tag in re.findall(r"\[(.*?)\]", tags)
    )
    ref_html = f'<span class="pr-ref">#{ref}</span>' if ref else ""
    initial = html.escape((commit.author.strip() or "?")[0].upper())
    return (
        f'<div class="g-row" style="--c: {author_color(commit.author)}"><span class="g-dot"></span>'
        f'<div class="g-card"><div class="g-title">{chips}'
        f'<span class="ctitle">{html.escape(text)}</span>{ref_html}</div>'
        f'<div class="g-meta"><code class="sha">{html.escape(commit.sha)}</code>'
        f'<span class="avatar">{initial}</span>{html.escape(commit.author)}'
        f"<span>{ago(commit.timestamp, now)}</span></div></div></div>"
    )


def render_graph(
    commits: list[Commit],
    deployed: str | None,
    behind: int | None,
    branch: str,
    now: float | None = None,
) -> str:
    """The graph: `origin/<branch>` on top, the missing commits, then the deployed commit."""
    now = time.time() if now is None else now
    rows = [
        f'<div class="g-row"><span class="g-dot end"></span><div><span class="branch">'
        f"origin/{html.escape(branch)}</span></div></div>"
    ]
    rows += [render_commit(commit, now) for commit in commits]
    if behind and behind > len(commits):
        rows.append(
            '<div class="g-row"><span class="g-dot"></span>'
            f'<span class="g-more">… et {behind - len(commits)} commits plus anciens</span></div>'
        )
    if deployed:
        rows.append(
            '<div class="g-row"><span class="g-dot end" style="--c: var(--ok)"></span><div>'
            '<span class="branch prod">production</span> '
            f'<code class="sha">{html.escape(deployed[:7])}</code></div></div>'
        )
    return f'<div class="graph">{"".join(rows)}</div>'
