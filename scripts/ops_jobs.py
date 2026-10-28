"""The jobs behind the previews page: reading the PRs and previews, running the scripts.

Everything here is standard library only and reads its project names from ops.toml
(scripts/ops_config.py). The page (scripts/ops_render.py) and the server (scripts/previews.py)
read the state kept here (`jobs`, `prod_job`); the action threads write it under `jobs_lock`.
Spec: docs/spec/04-configuration-et-deploiement.md, section "Previews des PR".
"""

import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.ops_config import CONFIG, REPO

PREVIEW_SH = REPO / CONFIG.previews_script
DEPLOY_SH = REPO / CONFIG.deploy_script
LOG_DIR = REPO / ".local" / "previews" / "logs"
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


# Running and last finished action of each PR, and of the production deploy; the page reads
# them, the action threads write them.
jobs: dict[int, Job] = {}
prod_job: Job | None = None
jobs_lock = threading.Lock()


def parse_previews(text: str) -> dict[int, Preview]:
    previews = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0].isdigit():
            pr = int(parts[0])
            previews[pr] = Preview(pr, int(parts[1]), parts[2], parts[3], parts[4])
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
    """The commit the deployed container was built from (image label), None if unknown."""
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
    count = run_text(["git", "rev-list", "--count", f"{deployed}..{origin}"])
    return int(count) if count and count.isdigit() else None


def log_path(pr: int) -> Path:
    return LOG_DIR / f"pr-{pr}.log"


PROD_LOG = LOG_DIR / "prod.log"


def run_logged(command: list[str], log, timeout: float) -> int:
    """Run `command` with its output in `log`; 127 if it cannot start, 124 if it is stopped on timeout."""
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
    job: Job, command: list[str], log_file: Path, timeout: float | None = None
) -> None:
    timeout = JOB_TIMEOUT_SECONDS if timeout is None else timeout

    def run() -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with log_file.open("w") as log:
            returncode = run_logged(command, log, timeout)
        with jobs_lock:
            job.returncode = returncode

    threading.Thread(target=run, daemon=True).start()


def start_job(pr: int, action: str) -> bool:
    """Run `preview.sh <action> <pr>` in the background; False when the PR already has one running."""
    with jobs_lock:
        current = jobs.get(pr)
        if current is not None and current.returncode is None:
            return False
        job = Job(action, time.time())
        jobs[pr] = job
    run_in_background(job, [str(PREVIEW_SH), action, str(pr)], log_path(pr))
    return True


def start_prod_deploy() -> bool:
    """Run `deploy.sh` in the background; False when a deploy is already running."""
    global prod_job
    with jobs_lock:
        if prod_job is not None and prod_job.returncode is None:
            return False
        prod_job = Job("deploy", time.time())
        job = prod_job
    run_in_background(job, [str(DEPLOY_SH)], PROD_LOG)
    return True


def start_sweep() -> None:
    threading.Thread(
        target=subprocess.run,
        args=([str(PREVIEW_SH), "sweep"],),
        kwargs={"cwd": REPO, "check": False, "capture_output": True},
        daemon=True,
    ).start()
