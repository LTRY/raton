"""The ops tool's jobs: the preview script contract, persisted jobs, the deploy lock.

Spec: docs/spec/04-configuration-et-deploiement.md, sections "Configuration de l'outil ops" and
"Deploiement de main".
"""

import json
import os
import subprocess
import sys
import time

import pytest
from ops import deploy_lock
from ops import jobs as ops_jobs
from ops.jobs import Job, Preview, parse_preview_line, parse_previews
from ops.render import preview_status, prod_status, render_page

REPO = ops_jobs.REPO
SHA = "a" * 40


# --- the contract of the previews script -----------------------------------------------------


@pytest.fixture
def fake_bin(tmp_path):
    """A PATH with a fake docker (prints $FAKE_PS for `ps`, logs its calls) and a fake gh."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    docker = bin_dir / "docker"
    docker.write_text(
        f'#!/bin/sh\necho "docker $*" >> {calls}\n[ "$1" = ps ] && printf "%s" "$FAKE_PS"\nexit 0\n'
    )
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\necho "gh $*" >> {calls}\necho "${{FAKE_PR_STATE:-OPEN}}"\n')
    for script in (docker, gh):
        script.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return env, calls


def run_preview_sh(env, *args, **extra):
    return subprocess.run(
        [str(ops_jobs.PREVIEW_SH), *args],
        cwd=REPO,
        env={**env, **extra},
        capture_output=True,
        text=True,
        check=False,
    )


def test_list_prints_one_valid_line_per_preview(fake_bin):
    env, _ = fake_bin
    ps = f"31|{SHA}|running|copy\n7|{SHA[:7]}|exited|\n12||created|shared\n"

    result = run_preview_sh(env, "list", FAKE_PS=ps)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"31 9031 {SHA} running copy",
        f"7 9007 {SHA[:7]} exited -",
        "12 9012 - created shared",
    ]
    previews, invalid = parse_previews(result.stdout)
    assert invalid == []
    assert sorted(previews) == [7, 12, 31]


def test_list_prints_nothing_without_previews(fake_bin):
    env, _ = fake_bin

    result = run_preview_sh(env, "list", FAKE_PS="")

    assert (result.returncode, result.stdout) == (0, "")


def test_sweep_keeps_the_previews_of_open_prs(fake_bin):
    env, calls = fake_bin

    result = run_preview_sh(env, "sweep", FAKE_PS=f"31|{SHA}|running|copy\n", FAKE_PR_STATE="OPEN")

    assert result.returncode == 0
    assert "compose" not in calls.read_text()  # nothing was removed


def test_bad_usage_exits_with_2_and_a_message_on_stderr(fake_bin):
    env, _ = fake_bin

    for args in ((), ("bogus",), ("up",), ("up", "abc"), ("down", "1x"), ("rebase",)):
        result = run_preview_sh(env, *args)
        assert result.returncode == 2, args
        assert result.stderr.strip(), args
        assert result.stdout == "", args


# --- parse_previews --------------------------------------------------------------------------


def test_parse_previews_reads_valid_lines():
    text = f"31 9031 {SHA} running copy\n\n7 9007 - exited -\n  8 9008 abcdef1 created shared  \n"

    previews, invalid = parse_previews(text)

    assert invalid == []
    assert previews[31] == Preview(31, 9031, SHA, "running", "copy")
    assert previews[7] == Preview(7, 9007, "-", "exited", "-")
    assert previews[8].sha == "abcdef1"


@pytest.mark.parametrize(
    "line",
    [
        "noise",
        f"31 9031 {SHA} running",  # 4 fields
        f"31 9031 {SHA} running copy extra",  # 6 fields
        f"x 9031 {SHA} running copy",  # PR not a number
        f"31 port {SHA} running copy",
        f"31 0 {SHA} running copy",  # port out of range
        f"31 70000 {SHA} running copy",
        f"31 9031 {'g' * 40} running copy",  # not hexadecimal
        "31 9031 abc running copy",  # too short to be a commit
        f"31 9031 {SHA} Running copy",  # state not lowercase
        f"31 9031 {SHA} running unknown",  # db outside shared|copy|-
        "²3 9031 - running -",  # non-ASCII digit
    ],
)
def test_parse_preview_line_rejects_invalid_lines(line):
    assert parse_preview_line(line) is None


def test_parse_previews_returns_the_invalid_lines_and_keeps_the_first_duplicate():
    text = f"31 9031 {SHA} running copy\nnoise\n31 9031 - exited -\n7 9007 - exited -\n"

    previews, invalid = parse_previews(text)

    assert sorted(previews) == [7, 31]
    assert previews[31].state == "running"
    assert invalid == ["noise", "31 9031 - exited -"]


def test_list_previews_warns_about_skipped_lines_and_a_failing_script(
    tmp_path, monkeypatch, capsys
):
    script = tmp_path / "preview.sh"
    script.write_text('#!/bin/sh\necho "7 9007 - exited -"\necho garbage\necho boom >&2\nexit 3\n')
    script.chmod(0o755)
    monkeypatch.setattr(ops_jobs, "PREVIEW_SH", script)

    previews, warning = ops_jobs.list_previews()

    assert sorted(previews) == [7]
    assert "code 3" in warning and "boom" in warning
    assert "1 ligne invalide ignorée" in warning and "garbage" in warning
    assert "garbage" in capsys.readouterr().err  # also in the container's journal


def test_list_previews_reports_a_script_that_cannot_start(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_jobs, "PREVIEW_SH", tmp_path / "missing.sh")

    previews, warning = ops_jobs.list_previews()

    assert previews == {}
    assert "Impossible de lancer" in warning


def test_list_previews_has_no_warning_for_a_clean_output(tmp_path, monkeypatch):
    script = tmp_path / "preview.sh"
    script.write_text('#!/bin/sh\necho "7 9007 - exited -"\n')
    script.chmod(0o755)
    monkeypatch.setattr(ops_jobs, "PREVIEW_SH", script)

    assert ops_jobs.list_previews()[1] is None


# --- persisted jobs --------------------------------------------------------------------------


@pytest.fixture
def job_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(ops_jobs, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(ops_jobs, "PROD_LOG", tmp_path / "logs" / "prod.log")
    monkeypatch.setattr(ops_jobs, "jobs", {})
    monkeypatch.setattr(ops_jobs, "prod_job", None)
    return tmp_path


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_a_job_saved_as_running_with_no_process_becomes_interrupted(job_state):
    ops_jobs.save_job(Job("up", 5.0, pr=31, pid=dead_pid()))
    ops_jobs.save_job(Job("deploy", 6.0, pid=dead_pid()))
    ops_jobs.save_job(Job("down", 7.0, pr=8))  # the page died before the script started

    ops_jobs.load_jobs()

    for job in (ops_jobs.jobs[31], ops_jobs.jobs[8], ops_jobs.prod_job):
        assert (job.returncode, job.interrupted) == (1, True)
    assert preview_status({}, None, ops_jobs.jobs[31]) == (
        "Interrompu (la page a redémarré)",
        "error",
    )
    assert prod_status(ops_jobs.prod_job)[1] == "error"
    assert "Interrompu" in (job_state / "logs" / "pr-31.log").read_text()
    assert "Interrompu" in ops_jobs.PROD_LOG.read_text()
    # The verdict itself is persisted.
    assert json.loads(ops_jobs.job_file(31).read_text())["interrupted"] is True


def test_finished_jobs_are_restored_as_they_were(job_state):
    ops_jobs.save_job(Job("up", 5.0, returncode=0, pr=31))
    ops_jobs.save_job(Job("deploy", 6.0, returncode=2))

    ops_jobs.load_jobs()

    assert ops_jobs.jobs[31] == Job("up", 5.0, returncode=0, pr=31)
    assert ops_jobs.prod_job.returncode == 2 and not ops_jobs.prod_job.interrupted


def test_a_reused_pid_does_not_keep_a_job_running(job_state):
    if ops_jobs.process_start(os.getpid()) is None:
        pytest.skip("needs /proc")
    ops_jobs.save_job(Job("up", 5.0, pr=31, pid=os.getpid(), pid_start="1"))

    ops_jobs.load_jobs()

    assert ops_jobs.jobs[31].interrupted


def test_a_job_whose_process_still_runs_is_watched_not_interrupted(job_state, monkeypatch):
    watched = []
    monkeypatch.setattr(ops_jobs, "watch_orphan", lambda job, timeout: watched.append(job.pr))
    ops_jobs.save_job(
        Job("up", 5.0, pr=31, pid=os.getpid(), pid_start=ops_jobs.process_start(os.getpid()))
    )

    ops_jobs.load_jobs()
    time.sleep(0.2)

    assert watched == [31]
    assert ops_jobs.jobs[31].returncode is None


def test_an_unreadable_job_file_is_ignored(job_state):
    ops_jobs.JOBS_DIR.mkdir(parents=True)
    (ops_jobs.JOBS_DIR / "pr-1.json").write_text("{not json")
    (ops_jobs.JOBS_DIR / "pr-2.json").write_text('{"unknown": 1}')

    ops_jobs.load_jobs()

    assert ops_jobs.jobs == {}


def test_a_started_job_is_persisted_with_its_pid_and_its_result(job_state, monkeypatch):
    script = job_state / "preview.sh"
    script.write_text("#!/bin/sh\nexit 3\n")
    script.chmod(0o755)
    monkeypatch.setattr(ops_jobs, "PREVIEW_SH", script)

    assert ops_jobs.start_job(31, "up")
    for _ in range(100):
        if ops_jobs.jobs[31].returncode is not None:
            break
        time.sleep(0.05)

    saved = json.loads(ops_jobs.job_file(31).read_text())
    assert saved["action"] == "up" and saved["pr"] == 31 and saved["returncode"] == 3
    assert isinstance(saved["pid"], int)


# --- the deploy lock -------------------------------------------------------------------------


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    path = tmp_path / "lock" / "deploy.lock"
    monkeypatch.setattr(deploy_lock, "LOCK_PATH", path)
    return path


def test_the_lock_is_exclusive_and_released_with_its_descriptor(lock_path):
    fd = deploy_lock.acquire()

    assert fd is not None
    assert deploy_lock.acquire() is None
    assert deploy_lock.is_held()

    os.close(fd)
    assert not deploy_lock.is_held()


def run_deploy_lock_cli(lock_path, *command):
    return subprocess.run(
        [sys.executable, str(REPO / "ops" / "deploy_lock.py"), *command],
        env={**os.environ, "DEPLOY_LOCK_PATH": str(lock_path)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_command_runs_under_the_lock_and_releases_it_when_done(lock_path):
    result = run_deploy_lock_cli(lock_path, "sh", "-c", f"test -e {lock_path} && echo ran")

    assert (result.returncode, result.stdout.strip()) == (0, "ran")
    assert not deploy_lock.is_held()


def test_the_command_does_not_start_while_the_lock_is_held(lock_path, tmp_path):
    fd = deploy_lock.acquire()
    marker = tmp_path / "marker"

    result = run_deploy_lock_cli(lock_path, "touch", str(marker))

    os.close(fd)
    assert result.returncode == deploy_lock.BUSY_EXIT_CODE == 75
    assert "déjà en cours" in result.stderr
    assert not marker.exists()


def test_deploy_sh_run_by_hand_fails_cleanly_while_a_deploy_holds_the_lock(lock_path):
    fd = deploy_lock.acquire()

    result = subprocess.run(
        [str(ops_jobs.DEPLOY_SH)],
        env={**os.environ, "DEPLOY_LOCK_PATH": str(lock_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    os.close(fd)
    assert result.returncode == 75
    assert "Un déploiement est déjà en cours : rien n'est déployé" in result.stderr


def test_the_button_does_not_start_a_second_deploy_while_the_lock_is_held(lock_path, job_state):
    fd = deploy_lock.acquire()

    started = ops_jobs.start_prod_deploy()
    elsewhere = ops_jobs.deploy_elsewhere(ops_jobs.prod_job)
    os.close(fd)

    assert started is False
    assert ops_jobs.prod_job is None  # no failed job was recorded
    assert elsewhere is True
    assert not ops_jobs.deploy_elsewhere(None)


def test_the_page_says_a_deploy_is_already_running_and_disables_the_button():
    page = render_page("nas:8999", [], {}, {}, None, deploy_elsewhere=True)

    assert "Déploiement déjà en cours (lancé hors de cette page)" in page
    assert '<button class="primary" disabled>Déployer main en production' in page
    assert 'http-equiv="refresh"' in page
    assert prod_status(Job("deploy", 0.0, returncode=0), elsewhere=True)[1] == "busy"
    assert prod_status(Job("deploy", 0.0), elsewhere=True) == ("Déploiement en cours…", "busy")


def test_the_page_shows_an_interrupted_deploy_as_a_failure():
    job = Job("deploy", 0.0, returncode=1, interrupted=True)

    assert prod_status(job) == ("Déploiement interrompu (la page a redémarré)", "error")
    assert "interrompu" in render_page("h", [], {}, {}, None, job)


def test_make_up_runs_under_the_deploy_lock():
    dry_run = subprocess.run(
        ["make", "-n", "up"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout

    assert "ops/deploy_lock.py" in dry_run and "up-locked" in dry_run


def test_a_nested_command_does_not_take_the_lock_again(lock_path):
    """deploy.sh runs `make up` inside its own lock: the inner call must go through."""
    fd = deploy_lock.acquire()
    try:
        result = subprocess.run(
            [sys.executable, str(REPO / "ops" / "deploy_lock.py"), "echo", "inner"],
            env={
                **os.environ,
                "DEPLOY_LOCK_PATH": str(lock_path),
                "DEPLOY_LOCK_HELD": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        os.close(fd)

    assert (result.returncode, result.stdout.strip()) == (0, "inner")


# --- hardening of the page's lookups ---------------------------------------------------------


def test_a_hung_list_script_is_stopped_with_its_children(tmp_path, monkeypatch):
    script = tmp_path / "preview.sh"
    script.write_text("#!/bin/sh\nsleep 60 &\nwait\n")
    script.chmod(0o755)
    monkeypatch.setattr(ops_jobs, "PREVIEW_SH", script)
    monkeypatch.setattr(ops_jobs, "LIST_TIMEOUT_SECONDS", 0.3)

    started = time.time()
    previews, warning = ops_jobs.list_previews()

    assert time.time() - started < 5
    assert previews == {}
    assert "n'a pas répondu" in warning


def test_page_lookups_are_cached_until_invalidated(monkeypatch):
    calls = []
    monkeypatch.setattr(ops_jobs, "_cache", {})
    monkeypatch.setattr(ops_jobs, "fetch_open_prs", lambda: calls.append(1) or ([], None))

    ops_jobs.list_open_prs()
    ops_jobs.list_open_prs()
    assert len(calls) == 1

    ops_jobs.invalidate_caches()
    ops_jobs.list_open_prs()
    assert len(calls) == 2


def test_a_finished_job_invalidates_the_caches(job_state, monkeypatch):
    script = job_state / "preview.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setattr(ops_jobs, "PREVIEW_SH", script)
    monkeypatch.setattr(ops_jobs, "_cache", {("prs",): (time.time(), "stale")})

    ops_jobs.start_job(31, "up")
    for _ in range(100):
        if ops_jobs.jobs[31].returncode is not None and not ops_jobs._cache:
            break
        time.sleep(0.05)

    assert ops_jobs._cache == {}
