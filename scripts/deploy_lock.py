"""The deploy lock: one deploy at a time, whoever starts it (the page's button or a hand-run deploy.sh).

Standard library only. The lock is an `fcntl.flock` on `.local/previews/deploy.lock`, held for as
long as the deploy runs. As a command, `python3 scripts/deploy_lock.py <command...>` takes the lock
without waiting, then replaces itself with the command (the open file keeps the lock until the
command and its children exit); exit code 75 and a French message when someone else holds it.
Spec: docs/spec/04-configuration-et-deploiement.md, section "Deploiement de main".
"""

import fcntl
import os
import sys
from pathlib import Path

# DEPLOY_LOCK_PATH lets the tests use another file.
LOCK_PATH = Path(
    os.environ.get("DEPLOY_LOCK_PATH")
    or Path(__file__).resolve().parent.parent / ".local" / "previews" / "deploy.lock"
)
BUSY_EXIT_CODE = 75  # EX_TEMPFAIL
BUSY_MESSAGE = "un déploiement est déjà en cours : rien n'est déployé"


def _open(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o644)


def acquire(path: Path | None = None) -> int | None:
    """The open descriptor holding the lock (closing it releases it), None when it is held."""
    fd = _open(path or LOCK_PATH)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def is_held(path: Path | None = None) -> bool:
    """Whether a deploy holds the lock right now."""
    fd = acquire(path)
    if fd is None:
        return True
    os.close(fd)
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: deploy_lock.py <command> [args...]", file=sys.stderr)
        return 2
    fd = acquire()
    if fd is None:
        print(f"deploy.sh: {BUSY_MESSAGE}", file=sys.stderr)
        return BUSY_EXIT_CODE
    os.set_inheritable(fd, True)  # the command keeps the lock for its whole run
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
