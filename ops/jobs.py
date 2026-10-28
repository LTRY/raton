"""The jobs behind the previews page: reading the PRs and previews, running the scripts.

Everything here is standard library only and reads its project names from ops.toml
(ops/config.py). The page (ops/render.py) and the server (ops/server.py)
read the state kept here (`jobs`, `prod_job`); the action threads write it under `jobs_lock`.
Spec: ops/docs/outil-ops.md, section "Previews des PR".
"""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ops import deploy_lock
from ops.config import CONFIG, REPO

PREVIEW_SH = REPO / CONFIG.previews_script
DEPLOY_SH = REPO / CONFIG.deploy_script
LOG_DIR = REPO / ".local" / "previews" / "logs"
# One JSON file per job (pr-<N>.json, prod.json), so a restarted page remembers them.
JOBS_DIR = REPO / ".local" / "previews" / "jobs"
# A job that never ends would keep its button disabled forever (ops.toml, [jobs] timeout_minutes).
JOB_TIMEOUT_SECONDS = CONFIG.job_timeout_minutes * 60


@dataclass
class Preview:
    """A preview container as `preview.sh list` reports it."""

    pr: int
    port: int
    sha: str
    state: str  # docker's container state: running, exited, created...
    db: str = "-"  # "shared" (the real DB), "copy" (a migrated copy), "-" when unknown


@dataclass
class Job:
    action: str  # "up", "rebase" or "down"; "deploy" for the production
    started: float
    returncode: int | None = None
    pr: int | None = None  # None for the production deploy
    pid: int | None = None  # the script's process, also its process group
    pid_start: str | None = None  # its start time (see process_start), to tell a reused pid
    interrupted: bool = False  # the page restarted while it ran: returncode is 1, nobody knows more


# Running and last finished action of each PR, and of the production deploy; the page reads
# them, the action threads write them.
jobs: dict[int, Job] = {}
prod_job: Job | None = None
jobs_lock = threading.Lock()


PREVIEW_STATE = re.compile(r"[a-z]+")
PREVIEW_SHA = re.compile(r"-|[0-9a-f]{7,40}")
PREVIEW_DB = ("shared", "copy", "-")


def parse_preview_line(line: str) -> Preview | None:
    """A preview from one line of `list` (`<pr> <port> <sha> <state> <db>`), None if it is invalid."""
    parts = line.split()
    if len(parts) != 5:
        return None
    pr, port, sha, state, db = parts
    if not (pr.isascii() and pr.isdigit() and port.isascii() and port.isdigit()):
        return None
    if not 0 < int(port) < 65536:
        return None
    if not (PREVIEW_SHA.fullmatch(sha) and PREVIEW_STATE.fullmatch(state) and db in PREVIEW_DB):
        return None
    return Preview(int(pr), int(port), sha, state, db)


def parse_previews(text: str) -> tuple[dict[int, Preview], list[str]]:
    """The previews of a `list` output, and its invalid lines (blank lines are not).

    An invalid line, or a second line for a PR already listed, is skipped but returned, so the
    caller can report it. Spec: "Contrat du script de previews".
    """
    previews: dict[int, Preview] = {}
    invalid = []
    for line in text.splitlines():
        if not line.strip():
            continue
        preview = parse_preview_line(line)
        if preview is None or preview.pr in previews:
            invalid.append(line.strip())
        else:
            previews[preview.pr] = preview
    return previews, invalid


# `list` runs on every refresh of the page: a hung docker must not freeze it.
LIST_TIMEOUT_SECONDS = 30


def run_list_script() -> tuple[int, str, str] | str:
    """(returncode, stdout, stderr) of `list`, or the French error when it cannot run to the end."""
    try:
        # Its own process group, so a timeout stops docker too, which would keep the pipes open.
        process = subprocess.Popen(
            [str(PREVIEW_SH), "list"],
            cwd=REPO,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        return f"Impossible de lancer {CONFIG.previews_script} list : {error}"
    try:
        stdout, stderr = process.communicate(timeout=LIST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return (
            f"{CONFIG.previews_script} list n'a pas répondu en {LIST_TIMEOUT_SECONDS} s : arrêté."
        )
    return process.returncode, stdout, stderr


def list_previews() -> tuple[dict[int, Preview], str | None]:
    """The previews, and a French warning when `list` failed or printed lines that were skipped."""
    outcome = run_list_script()
    if isinstance(outcome, str):
        print(outcome, file=sys.stderr, flush=True)
        return {}, outcome
    returncode, stdout, stderr = outcome
    previews, invalid = parse_previews(stdout)
    warnings = []
    if returncode != 0:
        detail = stderr.strip().splitlines()[-1:] or [""]
        warnings.append(
            f"{CONFIG.previews_script} list a échoué (code {returncode}) : {detail[0]}".rstrip(" :")
        )
    if invalid:
        plural = "s" if len(invalid) > 1 else ""
        warnings.append(
            f"{CONFIG.previews_script} list : {len(invalid)} ligne{plural} invalide{plural} "
            f"ignorée{plural} (première : « {invalid[0][:80]} »)"
        )
    warning = " ".join(warnings).strip() or None
    if warning:
        print(warning, file=sys.stderr, flush=True)
    return previews, warning


# The page refreshes every 4 s while a job runs: GitHub and Docker are asked at most this often
# (the "Rafraîchir" link and the end of a job skip the wait).
CACHE_TTL = 15.0
_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def cached(key: tuple, ttl: float, compute: Callable[[], object]) -> object:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and time.time() - hit[0] < ttl:
            return hit[1]
    value = compute()  # outside the lock: a slow gh must not block the other lookups
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


def invalidate_caches() -> None:
    global _origin_cache
    with _cache_lock:
        _cache.clear()
    _origin_cache = (0.0, None)


def list_open_prs() -> tuple[list[dict], str | None]:
    """The open PRs (cached for CACHE_TTL), and the error to show when `gh` cannot list them."""
    return cached(("prs",), CACHE_TTL, fetch_open_prs)


def fetch_open_prs() -> tuple[list[dict], str | None]:
    fields = "number,title,url,headRefName,headRefOid,isCrossRepository,isDraft,author"
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


def list_merged_prs(limit: int = 5) -> list[dict]:
    """The last merged PRs (cached for CACHE_TTL), for the board's last column; [] if `gh` fails."""
    return cached(("merged", limit), CACHE_TTL, lambda: fetch_merged_prs(limit))


def fetch_merged_prs(limit: int) -> list[dict]:
    out = run_text(
        ["gh", "pr", "list", "--state", "merged", "--limit", str(limit)]
        + ["--json", "number,title,url,author"]
    )
    return json.loads(out) if out else []


def run_text(command: list[str], timeout: float = 15) -> str | None:
    """Stdout of a command, None when it fails, times out or cannot start."""
    try:
        result = subprocess.run(
            command, cwd=REPO, capture_output=True, text=True, check=False, timeout=timeout
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def deployed_sha() -> str | None:
    """The commit the deployed container was built from (image label, cached), None if unknown."""
    return cached(("deployed",), CACHE_TTL, read_deployed_sha)


def read_deployed_sha() -> str | None:
    if not CONFIG.deploy_container or not CONFIG.deploy_sha_label:
        return None
    label_format = '{{ index .Config.Labels "' + CONFIG.deploy_sha_label + '" }}'
    sha = run_text(["docker", "inspect", "--format", label_format, CONFIG.deploy_container])
    return sha if sha and re.fullmatch(r"[0-9a-f]{40}", sha) else None


# `git fetch` on every refresh of the page (every 4 s while a job runs) would hammer GitHub.
ORIGIN_TTL = 30.0
_origin_cache: tuple[float, str | None] = (0.0, None)


def origin_main_sha() -> str | None:
    """The current head of origin/<deploy branch>, fetched at most every ORIGIN_TTL seconds."""
    global _origin_cache
    fetched_at, sha = _origin_cache
    if time.time() - fetched_at < ORIGIN_TTL:
        return sha
    run_text(["git", "fetch", "-q", "origin", CONFIG.deploy_branch], timeout=30)
    sha = run_text(["git", "rev-parse", f"origin/{CONFIG.deploy_branch}"])
    _origin_cache = (time.time(), sha)
    return sha


def commits_behind(deployed: str, origin: str) -> int | None:
    """How many commits origin/main has that the deployed commit lacks, None if git cannot say."""
    return cached(("behind", deployed, origin), CACHE_TTL, lambda: count_behind(deployed, origin))


def count_behind(deployed: str, origin: str) -> int | None:
    count = run_text(["git", "rev-list", "--count", f"{deployed}..{origin}"])
    return int(count) if count and count.isdigit() else None


def pending_commits(deployed: str, origin: str, limit: int = 15) -> list[tuple[str, str]]:
    """(short sha, title) of the newest commits origin/main has that the deployed one lacks."""
    return cached(
        ("pending", deployed, origin, limit),
        CACHE_TTL,
        lambda: read_pending(deployed, origin, limit),
    )


def read_pending(deployed: str, origin: str, limit: int) -> list[tuple[str, str]]:
    out = run_text(["git", "log", f"-{limit}", "--format=%h%x09%s", f"{deployed}..{origin}"])
    pairs = [line.partition("\t") for line in (out or "").splitlines()]
    return [(sha, title) for sha, _, title in pairs if sha]


def log_path(pr: int) -> Path:
    return LOG_DIR / f"pr-{pr}.log"


PROD_LOG = LOG_DIR / "prod.log"


def job_file(pr: int | None) -> Path:
    return JOBS_DIR / ("prod.json" if pr is None else f"pr-{pr}.json")


def save_job(job: Job) -> None:
    """Write the job's state; a disk error is reported but never stops the job itself."""
    path = job_file(job.pr)
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(job)))
        os.replace(temporary, path)  # atomic: a reader never sees half a file
    except OSError as error:
        print(f"Impossible d'enregistrer {path} : {error}", file=sys.stderr, flush=True)


def process_start(pid: int) -> str | None:
    """The start time of a process (field 22 of /proc/<pid>/stat), None where /proc has none."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The command name (field 2) may hold spaces and parentheses: read after the last one.
    return stat.rpartition(")")[2].split()[19]


def process_alive(job: Job) -> bool:
    """Whether the job's process still runs; a pid reused by another process counts as gone."""
    if job.pid is None:
        return False
    try:
        os.kill(job.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # exists, belongs to someone else
    start = process_start(job.pid)
    return not (job.pid_start and start and start != job.pid_start)


def finish_interrupted(job: Job) -> None:
    """Mark a job nobody is waiting for any more as failed and say so in its log."""
    with jobs_lock:
        job.returncode = 1
        job.interrupted = True
        save_job(job)
    log = PROD_LOG if job.pr is None else log_path(job.pr)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with log.open("a") as file:
            file.write("\nInterrompu : la page des previews a redémarré pendant ce job.\n")
    except OSError:
        pass


def watch_orphan(job: Job, timeout: float) -> None:
    """A job still running after a restart of the page: wait for its end, stop it on timeout."""
    deadline = job.started + timeout
    while process_alive(job):
        if time.time() > deadline:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not process_alive(job):
                    break
                os.killpg(job.pid, sig)
                time.sleep(10)
            break
        time.sleep(2)
    finish_interrupted(job)


def load_jobs() -> None:
    """Read the saved jobs at startup. A job saved as running whose process is gone becomes interrupted."""
    global prod_job
    for path in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = Job(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError) as error:
            print(f"Job ignoré, {path} illisible : {error}", file=sys.stderr, flush=True)
            continue
        with jobs_lock:
            if job.pr is None:
                prod_job = job
            else:
                jobs[job.pr] = job
        if job.returncode is not None:
            continue
        if process_alive(job):
            threading.Thread(
                target=watch_orphan, args=(job, JOB_TIMEOUT_SECONDS), daemon=True
            ).start()
        else:
            finish_interrupted(job)


def run_logged(
    command: list[str], log, timeout: float, on_start: Callable[[int], None] | None = None
) -> int:
    """Run `command` with its output in `log`; 127 if it cannot start, 124 if it is stopped on timeout.

    `on_start` receives the pid once the process runs.
    """
    try:
        # Its own process group: on timeout the whole tree (make, docker...) is stopped, not just the shell.
        process = subprocess.Popen(
            command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
    except OSError as error:
        # A script that cannot start (not executable...) must still end the job, or the
        # page shows it as running forever with an empty log.
        log.write(f"Impossible de lancer {command[0]} : {error}\n")
        return 127
    if on_start is not None:
        on_start(process.pid)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        log.write(f"\nArrêté au bout de {timeout / 60:.0f} min : le job ne se terminait pas.\n")
        log.flush()
        stop_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            stop_group(process, signal.SIGKILL)
            process.wait()
        return 124


def stop_group(process: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass  # already gone


def run_in_background(
    job: Job,
    command: list[str],
    log_file: Path,
    timeout: float | None = None,
    on_change: Callable[[Job], None] | None = None,
) -> None:
    """Run `command` in a thread; `on_change` is called with the job once its pid is known and once it ends."""
    timeout = JOB_TIMEOUT_SECONDS if timeout is None else timeout

    def started(pid: int) -> None:
        with jobs_lock:
            job.pid, job.pid_start = pid, process_start(pid)
            if on_change:
                on_change(job)

    def run() -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with log_file.open("w") as log:
            returncode = run_logged(command, log, timeout, started)
        with jobs_lock:
            job.returncode = returncode
            if on_change:
                on_change(job)
        invalidate_caches()  # the job changed what the page shows (a PR, a deployed commit)

    threading.Thread(target=run, daemon=True).start()


def start_job(pr: int, action: str) -> bool:
    """Run `preview.sh <action> <pr>` in the background; False when the PR already has one running."""
    with jobs_lock:
        current = jobs.get(pr)
        if current is not None and current.returncode is None:
            return False
        job = Job(action, time.time(), pr=pr)
        jobs[pr] = job
        save_job(job)
    run_in_background(job, [str(PREVIEW_SH), action, str(pr)], log_path(pr), on_change=save_job)
    return True


# The board's columns, left to right; a PR is moved to one by `move_pr`.
COLUMNS = ("draft", "todo", "preview", "merged")

# Why the last move failed, shown once by the page (the move runs inside a form post).
flash_error: str | None = None


def run_gh(args: list[str]) -> str | None:
    """Run `gh <args>`; the error text to show when it fails, None when it worked."""
    try:
        result = subprocess.run(
            ["gh", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except OSError, subprocess.TimeoutExpired:
        return f"gh {' '.join(args)} n'a pas pu s'exécuter."
    if result.returncode != 0:
        return f"gh {' '.join(args)} a échoué : {result.stderr.strip()}"
    return None


def move_pr(number: int, target: str) -> str | None:
    """Move a PR to a board column; the error to show when it cannot, None when done.

    draft: marks the PR as draft. todo: ready for review, its preview (if any) removed.
    preview: ready for review, preview (re)built. merged: squash-merged, then the previews of
    closed PRs are swept.
    """
    if target not in COLUMNS:
        return f"Colonne inconnue : {target}"
    prs, error = fetch_open_prs()
    pr = next((p for p in prs if p["number"] == number), None)
    if pr is None:
        return error or f"La PR {number} n'est pas ouverte."
    invalidate_caches()
    draft = pr.get("isDraft", False)
    if target == "draft":
        return None if draft else run_gh(["pr", "ready", str(number), "--undo"])
    if target == "merged":
        if draft:
            return "Une PR en draft ne se merge pas : sortez-la d'abord du draft."
        failure = run_gh(["pr", "merge", str(number), "--squash"])
        if failure is None:
            start_sweep()
        return failure
    if target == "preview" and pr.get("isCrossRepository"):
        return "Fork : pas de preview (son code tournerait sur cette machine)."
    if draft and (failure := run_gh(["pr", "ready", str(number)])):
        return failure
    if target == "preview":
        start_job(number, "up")
    elif number in list_previews()[0]:
        start_job(number, "down")
    return None


def deploy_elsewhere(prod: Job | None) -> bool:
    """Whether a deploy runs that this page did not start (a hand-run deploy.sh)."""
    return (prod is None or prod.returncode is not None) and deploy_lock.is_held()


def start_prod_deploy() -> bool:
    """Run `deploy.sh` in the background; False when a deploy is already running, here or elsewhere."""
    global prod_job
    with jobs_lock:
        if prod_job is not None and prod_job.returncode is None:
            return False
        if deploy_lock.is_held():
            return False
        prod_job = Job("deploy", time.time())
        job = prod_job
        save_job(job)
    run_in_background(job, [str(DEPLOY_SH)], PROD_LOG, on_change=save_job)
    return True


def start_sweep() -> None:
    threading.Thread(
        target=subprocess.run,
        args=([str(PREVIEW_SH), "sweep"],),
        kwargs={"cwd": REPO, "check": False, "capture_output": True},
        daemon=True,
    ).start()
