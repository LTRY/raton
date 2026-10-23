"""The daily log review of the `raton-ops` container: runs the `review-logs` skill with Claude Code.

Started by the previews page (scripts/previews.py --scheduler): a thread wakes once a day at
OPS_REVIEW_HOUR, runs `claude --bare -p "/review-logs 24"` in the repository and stores the verdict
and its cost in .local/ops/reviews/ (one JSON file per run), shown by the page.
Standard library only, like the page. Spec: docs/spec/13-jobs-logs-planification.md, section
"Revue quotidienne des journaux".
"""

import html
import json
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REVIEW_DIR = REPO / ".local" / "ops" / "reviews"

DEFAULT_HOUR = 8
DEFAULT_HOURS = 24
DEFAULT_MAX_USD = 1.0
RUN_TIMEOUT_SECONDS = 20 * 60
TICK_SECONDS = 30

# The skill is read-only: the CLI may read files and run the digest and the log queries, nothing
# else. The docker commands are the skill's fallback when the journal is missing.
ALLOWED_TOOLS = [
    "Read",
    "Skill",
    "Bash(python -m back.core.logs_digest:*)",
    "Bash(jq:*)",
    "Bash(grep:*)",
    "Bash(ls:*)",
    "Bash(tail:*)",
    "Bash(head:*)",
    "Bash(docker ps:*)",
    "Bash(docker compose logs:*)",
]


@dataclass
class Review:
    id: str  # file stem: <YYYY-MM-DD>-<HHMMSS>
    started: str  # ISO 8601, local time of the container
    trigger: str  # "scheduled" or "manual"
    hours: int
    ok: bool
    cost_usd: float | None
    duration_ms: int | None
    text: str  # the skill's verdict (Markdown), or the reason the run failed


# The review being run, if any; the page reads it, the run thread writes it.
running_since: float | None = None
running_lock = threading.Lock()


def build_command(hours: int, model: str | None, max_usd: float) -> list[str]:
    # --bare: the repository's hooks (SessionStart syncs the checkout) must not run here, and
    # the only accepted credential is ANTHROPIC_API_KEY. Skills still resolve through /name.
    command = [
        "claude",
        "--bare",
        "-p",
        f"/review-logs {hours}",
        "--output-format",
        "json",
        "--max-budget-usd",
        str(max_usd),
        "--allowedTools",
        *ALLOWED_TOOLS,
    ]
    if model:
        command += ["--model", model]
    return command


def parse_output(stdout: str) -> tuple[str, float | None, int | None, bool]:
    """(text, cost in USD, duration in ms, ok) from `claude -p --output-format json`."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip(), None, None, False
    if not isinstance(data, dict):
        return stdout.strip(), None, None, False
    cost = data.get("total_cost_usd")
    duration = data.get("duration_ms")
    return (
        str(data.get("result") or "").strip(),
        float(cost) if isinstance(cost, int | float) else None,
        int(duration) if isinstance(duration, int | float) else None,
        not data.get("is_error", False),
    )


def execute_review(hours: int, trigger: str, now: datetime | None = None) -> Review:
    """Run the skill and store the result; a failed run is stored too, with its reason."""
    now = now or datetime.now()
    review = Review(
        id=now.strftime("%Y-%m-%d-%H%M%S"),
        started=now.isoformat(timespec="seconds"),
        trigger=trigger,
        hours=hours,
        ok=False,
        cost_usd=None,
        duration_ms=None,
        text="",
    )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        review.text = "ANTHROPIC_API_KEY est absente de l'environnement du conteneur raton-ops."
    else:
        command = build_command(
            hours,
            os.environ.get("OPS_REVIEW_MODEL", "sonnet"),
            float(os.environ.get("OPS_REVIEW_MAX_USD") or DEFAULT_MAX_USD),
        )
        try:
            result = subprocess.run(
                command,
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            review.text = f"Impossible de lancer la revue : {error}"
        else:
            review.text, review.cost_usd, review.duration_ms, review.ok = parse_output(
                result.stdout
            )
            if result.returncode != 0:
                review.ok = False
            if not review.text:
                review.text = result.stderr.strip() or "La revue n'a rien renvoyé."
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / f"{review.id}.json").write_text(json.dumps(asdict(review), ensure_ascii=False))
    return review


def start_review(hours: int, trigger: str) -> bool:
    """Run a review in the background; False when one is already running."""
    global running_since
    with running_lock:
        if running_since is not None:
            return False
        running_since = time.time()

    def run() -> None:
        global running_since
        try:
            execute_review(hours, trigger)
        finally:
            with running_lock:
                running_since = None

    threading.Thread(target=run, daemon=True).start()
    return True


def list_reviews(limit: int | None = None) -> list[Review]:
    """The stored reviews, newest first."""
    if not REVIEW_DIR.is_dir():
        return []
    reviews = []
    for path in sorted(REVIEW_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            reviews.append(Review(**json.loads(path.read_text())))
        except OSError, ValueError, TypeError:
            continue  # a half-written or foreign file must not break the page
    return reviews


def read_review(review_id: str) -> Review | None:
    # The id comes from a URL: only the file-stem shape is looked up, never a path.
    if len(review_id) != 17 or not review_id.replace("-", "").isdigit():
        return None
    try:
        return Review(**json.loads((REVIEW_DIR / f"{review_id}.json").read_text()))
    except OSError, ValueError, TypeError:
        return None


def is_due(now: datetime, hour: int, reviews: list[Review]) -> bool:
    """True from `hour` o'clock on, until a scheduled review exists for today.

    Checking the wall clock rather than sleeping until 08:00 also catches up after the machine
    slept through the hour, or the container was restarted later in the day.
    """
    if now.hour < hour:
        return False
    today = now.date().isoformat()
    return not any(r.trigger == "scheduled" and r.started.startswith(today) for r in reviews)


def cost_since(reviews: list[Review], now: datetime, days: int) -> float:
    cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
    return sum(r.cost_usd or 0.0 for r in reviews if r.started >= cutoff)


def scheduler_loop() -> None:
    hour = int(os.environ.get("OPS_REVIEW_HOUR") or DEFAULT_HOUR)
    hours = int(os.environ.get("OPS_REVIEW_HOURS") or DEFAULT_HOURS)
    while True:
        if is_due(datetime.now(), hour, list_reviews(limit=50)):
            start_review(hours, "scheduled")
        time.sleep(TICK_SECONDS)


def start_scheduler() -> None:
    threading.Thread(target=scheduler_loop, daemon=True).start()


def format_cost(cost: float | None) -> str:
    return "coût inconnu" if cost is None else f"{cost:.2f} $".replace(".", ",")


def format_started(started: str) -> str:
    return datetime.fromisoformat(started).strftime("%d/%m/%Y à %H:%M")


def verdict_line(review: Review) -> str:
    return next((line.strip("*# ") for line in review.text.splitlines() if line.strip()), "")


def render_reviews(reviews: list[Review], busy: bool, now: datetime | None = None) -> str:
    """The "Revue des journaux" card of the previews page."""
    now = now or datetime.now()
    hour = int(os.environ.get("OPS_REVIEW_HOUR") or DEFAULT_HOUR)
    if busy:
        status, css = "Revue en cours…", "busy"
    elif not reviews:
        status, css = "Aucune revue pour l'instant", "none"
    else:
        last = reviews[0]
        status = (
            f"{format_started(last.started)} · {format_cost(last.cost_usd)} · {verdict_line(last)}"
        )
        css = "ok" if last.ok else "error"
    disabled = " disabled" if busy else ""
    rows = "".join(
        f'<li><a href="/reviews/{r.id}">{html.escape(format_started(r.started))}</a> · '
        f"{format_cost(r.cost_usd)} · "
        f"{'manuelle' if r.trigger == 'manual' else 'planifiée'}"
        f"{'' if r.ok else ' · échec'}</li>"
        for r in reviews[:7]
    )
    total = format_cost(cost_since(reviews, now, 30))
    return (
        '<div class="pr prod"><div class="info"><h2>Revue des journaux</h2>'
        f'<div class="meta">Tous les jours à {hour} h : le skill review-logs relit les '
        f"{DEFAULT_HOURS} dernières heures. Coût des 30 derniers jours : {total}.</div>"
        f'<div class="status {css}">{html.escape(status)}</div>'
        f'<ul class="meta reviews">{rows}</ul></div>'
        '<div class="actions"><form method="post" action="/reviews/run">'
        f'<button class="primary"{disabled}>Analyser maintenant</button></form></div></div>'
    )
