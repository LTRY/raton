import json
import time

from ops.jobs import Job, Preview, parse_previews
from ops.render import (
    preview_status,
    preview_url,
    prod_status,
    render_page,
    version_status,
)
from ops.server import same_origin

OPEN_PR = {
    "number": 31,
    "title": "Une PR <ouverte>",
    "url": "https://github.com/LTRY/raton/pull/31",
    "headRefName": "branche",
    "headRefOid": "a" * 40,
    "isCrossRepository": False,
    "author": {"login": "someone"},
}


def test_parse_previews_reads_the_lines_of_preview_sh_list():
    previews, invalid = parse_previews(f"31 9031 {'a' * 40} running copy\n7 9007 - exited -\n")

    assert invalid == []
    assert previews == {
        31: Preview(31, 9031, "a" * 40, "running", "copy"),
        7: Preview(7, 9007, "-", "exited", "-"),
    }


def test_preview_status_compares_the_running_commit_with_the_pr_head():
    up_to_date = Preview(31, 9031, "a" * 40, "running")
    behind = Preview(31, 9031, "b" * 40, "running")

    assert preview_status(OPEN_PR, up_to_date, None) == ("En ligne (aaaaaaa)", "ok")
    assert preview_status(OPEN_PR, behind, None)[1] == "stale"
    assert preview_status(OPEN_PR, None, None) == ("", "none")  # no preview: nothing to say
    assert preview_status(OPEN_PR, None, Job("up", 0.0))[1] == "busy"
    assert preview_status(OPEN_PR, up_to_date, Job("up", 0.0, returncode=1))[1] == "error"
    assert preview_status(OPEN_PR, None, Job("down", 0.0)) == ("Suppression…", "busy")


def test_a_form_from_another_site_is_refused():
    assert same_origin(None, "nas:8999")
    assert same_origin("http://nas:8999", "nas:8999")
    assert not same_origin("http://evil.example", "nas:8999")


def test_preview_url_keeps_the_hostname_of_the_page():
    assert preview_url("nas.local:8999", 9031) == "http://nas.local:9031/"
    assert preview_url(None, 9031) == "http://127.0.0.1:9031/"


def test_page_escapes_titles_and_lists_previews_of_closed_prs():
    page = render_page(
        "nas:8999",
        [OPEN_PR, {**OPEN_PR, "number": 32, "isCrossRepository": True}],
        {5: Preview(5, 9005, "c" * 40, "running", "shared")},
        {},
        None,
    )

    assert "Une PR &lt;ouverte&gt;" in page
    assert 'action="/prs/31/up"' not in page  # deploying is dragging the card, not a button
    assert 'action="/prs/5/down"' in page
    assert "/rebase" not in page
    assert 'href="http://nas:9005/"' in page
    assert "DB réelle" in page
    assert "http-equiv" not in page  # no auto-refresh while nothing is building


def test_refresh_and_production_deploy_sit_above_the_prs():
    page = render_page("nas:8999", [OPEN_PR], {}, {}, None)

    deploy = page.index('action="/prod/deploy"')
    assert page.index(">Rafraîchir<") < deploy < page.index('data-pr="31"')
    assert "return confirm(" in page  # a stray tap must not rebuild the real stack
    assert 'href="/prod/log"' not in page  # no journal before a first deploy


def test_a_running_production_deploy_disables_the_button_and_refreshes_the_page():
    page = render_page("nas:8999", [], {}, {}, None, Job("deploy", 0.0))

    assert "Déploiement en cours…" in page
    assert '<button class="primary" disabled>Déployer main en production' in page
    assert 'http-equiv="refresh"' in page
    assert 'href="/prod/log"' in page


def test_prod_status_reports_the_last_deploy():
    assert prod_status(None)[1] == "none"
    assert prod_status(Job("deploy", 0.0, returncode=0)) == ("Déployée", "ok")
    assert prod_status(Job("deploy", 0.0, returncode=2)) == ("Échec du déploiement", "error")


def test_scripts_run_by_the_previews_page_are_executable():
    import os

    from ops.jobs import DEPLOY_SH, PREVIEW_SH

    for script in (DEPLOY_SH, PREVIEW_SH):
        assert os.access(script, os.X_OK), f"{script} must be executable (git mode 100755)"


def test_a_script_that_cannot_start_ends_the_job_with_an_error(tmp_path):
    from ops.jobs import run_in_background

    job = Job("deploy", 0.0)
    log_file = tmp_path / "prod.log"
    run_in_background(job, [str(tmp_path / "missing.sh")], log_file)

    for _ in range(100):
        if job.returncode is not None:
            break
        time.sleep(0.05)
    assert job.returncode == 127
    assert "Impossible de lancer" in log_file.read_text()


def test_page_shows_the_reviews_card_only_when_the_scheduler_is_on():
    without = render_page("h", [], {}, {}, None)
    with_card = render_page("h", [], {}, {}, None, None, [], False)

    assert "Revue des journaux" not in without
    assert "Revue des journaux" in with_card


def test_version_status_compares_the_deployed_commit_with_origin_main():
    old, new = "a" * 40, "b" * 40

    assert version_status(new, new, 0) == ("À jour avec origin/main (bbbbbbb)", "ok")
    assert version_status(old, new, 2)[1] == "stale"
    assert "2 commits" in version_status(old, new, 2)[0]
    assert "1 commit :" in version_status(old, new, 1)[0]
    assert version_status(old, new, None)[1] == "stale"
    assert version_status(None, new, None)[1] == "none"
    assert version_status(old, None, None)[1] == "none"


def test_production_card_shows_the_version_line():
    page = render_page("h", [], {}, {}, None, prod_version=("En retard <de 2>", "stale"))

    assert "En retard &lt;de 2&gt;" in page


def test_a_job_that_never_ends_is_stopped_with_its_children(tmp_path):
    from ops.jobs import run_in_background

    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 60 &\nwait\n")
    script.chmod(0o755)
    job = Job("deploy", 0.0)
    log_file = tmp_path / "prod.log"
    run_in_background(job, [str(script)], log_file, timeout=0.3)

    for _ in range(200):
        if job.returncode is not None:
            break
        time.sleep(0.05)
    assert job.returncode == 124
    assert "Arrêté" in log_file.read_text()


def test_the_page_asks_for_the_token_only_when_one_is_set():
    from base64 import b64encode

    from ops.server import authorized

    def basic(user_and_password: str) -> str:
        return "Basic " + b64encode(user_and_password.encode()).decode()

    assert authorized(None, "")
    assert not authorized(None, "secret")
    assert not authorized("Bearer secret", "secret")
    assert not authorized("Basic !!!", "secret")
    assert not authorized(basic("ops:wrong"), "secret")
    assert authorized(basic("ops:secret"), "secret")
    assert authorized(basic(":secret"), "secret")
    assert authorized(basic("ops:se:cret"), "se:cret")


def column(page: str, key: str) -> str:
    """The HTML of one board column."""
    start = page.index(f'data-col="{key}"')
    ends = [i for i in (page.find("<section", start), page.find("</div><script>", start)) if i > 0]
    return page[start : min(ends)]


def test_board_sorts_prs_into_draft_todo_and_preview_columns():
    draft = {**OPEN_PR, "number": 40, "title": "Brouillon", "isDraft": True}
    ready = {**OPEN_PR, "number": 41, "title": "Prête", "isDraft": False}
    deployed = {**OPEN_PR, "number": 42, "title": "Déployée", "isDraft": False}
    previews = {42: Preview(42, 9042, "a" * 40, "running", "copy")}
    merged = [{"number": 7, "title": "Déjà mergée", "url": "https://x/7"}]

    page = render_page("nas:8999", [draft, ready, deployed], previews, {}, None, merged=merged)

    assert "Brouillon" in column(page, "draft")
    assert "Prête" in column(page, "todo")
    assert "Déployée" in column(page, "preview")
    assert "Déjà mergée" in column(page, "merged")
    assert "data-pr=" not in column(page, "merged")  # a merged PR does not move
    assert 'data-pr="40"' in column(page, "draft")


def test_a_building_preview_already_sits_in_the_preview_column():
    page = render_page("h", [OPEN_PR], {}, {31: Job("up", 0.0, pr=31)}, None)

    assert "Une PR &lt;ouverte&gt;" in column(page, "preview")


def test_only_cards_of_the_repository_can_be_dragged():
    page = render_page("h", [{**OPEN_PR, "isCrossRepository": True}], {}, {}, None)

    assert 'data-pr="31"' not in page  # a fork is read-only: no drag
    assert "/prs/31/move" not in page
    assert "Déplacer" not in page  # no menu: moving is dragging only
    assert "/prs/' + card.dataset.pr + '/move" in render_page("h", [], {}, {}, None)


def test_orphan_previews_stay_outside_the_board():
    page = render_page("h", [], {5: Preview(5, 9005, "c" * 40, "running", "shared")}, {}, None)

    assert "Previews de PR fermées" in page
    assert "/prs/5/move" not in page


def test_moving_to_draft_marks_the_pr_as_draft(monkeypatch):
    from ops import jobs

    calls = []
    monkeypatch.setattr(jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isDraft": False}], None))
    monkeypatch.setattr(jobs, "run_gh", lambda args: calls.append(args))

    assert jobs.move_pr(31, "draft") is None
    assert calls == [["pr", "ready", "31", "--undo"]]


def test_moving_a_draft_to_preview_readies_it_then_builds_the_preview(monkeypatch):
    from ops import jobs

    calls, started = [], []
    monkeypatch.setattr(jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isDraft": True}], None))
    monkeypatch.setattr(jobs, "run_gh", lambda args: calls.append(args))
    monkeypatch.setattr(jobs, "start_job", lambda pr, action: started.append((pr, action)))

    assert jobs.move_pr(31, "preview") is None
    assert calls == [["pr", "ready", "31"]]
    assert started == [(31, "up")]


def test_moving_back_to_todo_removes_the_preview(monkeypatch):
    from ops import jobs

    started = []
    monkeypatch.setattr(jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isDraft": False}], None))
    monkeypatch.setattr(
        jobs, "list_previews", lambda: ({31: Preview(31, 9031, "a" * 40, "running")}, None)
    )
    monkeypatch.setattr(jobs, "start_job", lambda pr, action: started.append((pr, action)))

    assert jobs.move_pr(31, "todo") is None
    assert started == [(31, "down")]


def test_a_draft_or_a_fork_cannot_be_merged_nor_previewed(monkeypatch):
    from ops import jobs

    monkeypatch.setattr(jobs, "run_gh", lambda args: pytest_fail())
    monkeypatch.setattr(jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isDraft": True}], None))
    assert "draft" in jobs.move_pr(31, "merged")
    monkeypatch.setattr(
        jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isCrossRepository": True}], None)
    )
    assert "Fork" in jobs.move_pr(31, "preview")
    assert "inconnue" in jobs.move_pr(31, "elsewhere")


def pytest_fail():
    raise AssertionError("gh must not be called")


def test_merging_squashes_the_pr_then_sweeps_the_previews(monkeypatch):
    from ops import jobs

    calls, swept = [], []
    monkeypatch.setattr(jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isDraft": False}], None))
    monkeypatch.setattr(jobs, "run_gh", lambda args: calls.append(args))
    monkeypatch.setattr(jobs, "start_sweep", lambda: swept.append(True))

    assert jobs.move_pr(31, "merged") is None
    assert calls == [["pr", "merge", "31", "--squash"]]
    assert swept == [True]


def test_a_failed_gh_call_is_reported_and_nothing_follows(monkeypatch):
    from ops import jobs

    monkeypatch.setattr(jobs, "fetch_open_prs", lambda: ([{**OPEN_PR, "isDraft": False}], None))
    monkeypatch.setattr(jobs, "run_gh", lambda args: "gh pr merge a échoué : conflits")
    monkeypatch.setattr(jobs, "start_sweep", lambda: pytest_fail())

    assert jobs.move_pr(31, "merged") == "gh pr merge a échoué : conflits"


def test_stale_production_alert_draws_the_missing_commits_as_a_graph():
    from ops.jobs import Commit

    pending = [
        Commit("abc1234", "[FRONT][BACK] Stats: link <channels> (#80)", "Ada", 1_000_000),
        Commit("def5678", "Plain title", "Bob", 1_000_000 - 7200),
    ]
    page = render_page(
        "h",
        [],
        {},
        {},
        None,
        prod_version=("En retard de 5 commits", "stale"),
        pending_commits=pending,
        deployed="b" * 40,
        behind=5,
    )

    assert "La production est en retard" in page
    assert 'class="sha">abc1234' in page
    assert '<span class="tag">FRONT</span><span class="tag">BACK</span>' in page
    assert "Stats: link &lt;channels&gt;" in page
    assert '<span class="pr-ref">#80</span>' in page
    assert "Plain title" in page
    assert '<span class="avatar">A</span>Ada' in page
    assert "origin/main" in page  # the branch on top
    assert '<span class="branch prod">production</span> <code class="sha">bbbbbbb' in page
    assert "… et 3 commits plus anciens" in page  # 5 behind, 2 drawn


def test_age_is_written_in_french():
    from ops.graph import ago

    assert ago(100, 130) == "à l'instant"
    assert ago(0, 600) == "il y a 10 min"
    assert ago(0, 7300) == "il y a 2 h"
    assert ago(0, 3 * 86400) == "il y a 3 j"
    assert ago(0, 70 * 86400) == "il y a 2 mois"


def test_an_author_keeps_the_same_colour():
    from ops.graph import author_color

    assert author_color("Ada") == author_color("Ada")
    assert author_color("Ada") != author_color("Bob")


def test_pending_commits_are_read_from_git_log(monkeypatch):
    from ops import jobs

    monkeypatch.setattr(
        jobs, "run_text", lambda command: "abc1234\t[OPS] Title\tAda\t100\nbroken line\n"
    )

    assert jobs.read_pending("d", "o", 15) == [jobs.Commit("abc1234", "[OPS] Title", "Ada", 100)]


def test_up_to_date_production_shows_no_alert():
    page = render_page("h", [], {}, {}, None, prod_version=("À jour", "ok"), pending_commits=[])

    assert 'class="alert"' not in page
    assert "À jour" in page


def test_a_card_without_preview_shows_no_status_line():
    page = render_page("h", [OPEN_PR], {}, {}, None)

    assert "Pas de preview" not in page
    assert 'class="status' not in column(page, "todo")


def test_merged_column_keeps_only_prs_the_production_lacks(monkeypatch):
    from ops import jobs

    merged = [
        {"number": 9, "title": "Live", "mergeCommit": {"oid": "a" * 40}},
        {"number": 8, "title": "Not live", "mergeCommit": {"oid": "b" * 40}},
        {"number": 7, "title": "No commit", "mergeCommit": None},
    ]
    # git says "ancestor" (empty output, exit 0) only for the PR already deployed
    monkeypatch.setattr(
        jobs,
        "run_text",
        lambda command: (
            json.dumps(merged) if command[0] == "gh" else ("" if command[3] == "a" * 40 else None)
        ),
    )

    assert [pr["number"] for pr in jobs.fetch_merged_prs("d" * 40, 30)] == [8, 7]
    assert len(jobs.fetch_merged_prs(None, 30)) == 3  # unknown deployed commit: the last few
