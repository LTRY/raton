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
.graph { --g-bg: #15171c; --g-line: #2a2d36; --g-text: #e8eaf0; --g-muted: #8b90a0;
  position: relative; margin-top: 12px; padding: 10px 12px; background: var(--g-bg); color: var(--g-text);
  border: 1px solid var(--g-line); border-radius: 12px; overflow: hidden; }
.graph::before { content: ""; position: absolute; left: 29px; top: 26px; bottom: 26px; width: 2px;
  background: linear-gradient(#7aa2ff, #3a4a78 70%, #3fae68); opacity: .8; }
.g-row { position: relative; display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 0 10px;
  align-items: center; padding: 7px 4px; border-radius: 8px; }
.g-row:hover { background: rgba(255,255,255,.04); }
.g-dot { justify-self: center; width: 12px; height: 12px; box-sizing: border-box; border-radius: 50%;
  background: var(--c, #7aa2ff); box-shadow: 0 0 0 4px var(--g-bg); z-index: 1; }
.g-dot.end { width: 16px; height: 16px; background: #7aa2ff; }
.g-dot.prod { background: #3fae68; }
.g-main { display: flex; flex-wrap: wrap; gap: 3px 7px; align-items: baseline; min-width: 0; }
.ctitle { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.g-meta { display: flex; gap: 8px; align-items: center; color: var(--g-muted); font-size: 12px; white-space: nowrap; }
.g-meta .sha { order: 3; }
.sha { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: #9db9ff; }
.tag { font-size: 10px; font-weight: 700; letter-spacing: .04em; background: rgba(122,162,255,.18); color: #9db9ff;
  border-radius: 5px; padding: 1px 6px; }
.pr-ref { color: var(--g-muted); font-size: 12px; }
.avatar { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%;
  background: var(--c); color: #fff; font-size: 10px; font-weight: 700; }
.branch { font-weight: 700; font-size: 12px; border-radius: 6px; padding: 2px 9px; color: #fff; background: #3b63c9; }
.branch.prod { background: #2f8f55; }
.g-more { color: var(--g-muted); font-size: 12px; }
@media (max-width: 700px) {
  .g-row { grid-template-columns: 28px minmax(0, 1fr); }
  .g-meta { grid-column: 2; flex-wrap: wrap; margin-top: 3px; }
}
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
        f'<div class="g-main">{chips}<span class="ctitle">{html.escape(text)}</span>{ref_html}</div>'
        f'<div class="g-meta"><span class="avatar">{initial}</span>{html.escape(commit.author)}'
        f'<span>{ago(commit.timestamp, now)}</span><code class="sha">{html.escape(commit.sha)}</code></div></div>'
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
            '<div class="g-row"><span class="g-dot end prod"></span><div>'
            '<span class="branch prod">production</span> '
            f'<code class="sha">{html.escape(deployed[:7])}</code></div></div>'
        )
    return f'<div class="graph">{"".join(rows)}</div>'
