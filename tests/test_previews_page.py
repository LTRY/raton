import time

from scripts.previews import (
    Job,
    Preview,
    parse_previews,
    preview_status,
    preview_url,
    prod_status,
    render_page,
    same_origin,
)

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
    previews = parse_previews(f"31 9031 {'a' * 40} running copy\n7 9007 - exited -\nnoise\n")

    assert previews == {
        31: Preview(31, 9031, "a" * 40, "running", "copy"),
        7: Preview(7, 9007, "-", "exited", "-"),
    }


def test_preview_status_compares_the_running_commit_with_the_pr_head():
    up_to_date = Preview(31, 9031, "a" * 40, "running")
    behind = Preview(31, 9031, "b" * 40, "running")

    assert preview_status(OPEN_PR, up_to_date, None) == ("En ligne (aaaaaaa)", "ok")
    assert preview_status(OPEN_PR, behind, None)[1] == "stale"
    assert preview_status(OPEN_PR, None, None) == ("Pas de preview", "none")
    assert preview_status(OPEN_PR, None, Job("up", 0.0))[1] == "busy"
    assert preview_status(OPEN_PR, up_to_date, Job("up", 0.0, returncode=1))[1] == "error"


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
    assert 'action="/prs/31/up"' in page
    assert 'action="/prs/32/up"' not in page  # a fork never gets a deploy button
    assert 'action="/prs/5/down"' in page
    assert 'href="http://nas:9005/"' in page
    assert "DB réelle" in page
    assert "http-equiv" not in page  # no auto-refresh while nothing is building


def test_refresh_and_production_deploy_sit_above_the_prs():
    page = render_page("nas:8999", [OPEN_PR], {}, {}, None)

    deploy = page.index('action="/prod/deploy"')
    assert page.index(">Rafraîchir<") < deploy < page.index('action="/prs/31/up"')
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

    from scripts.previews import DEPLOY_SH, PREVIEW_SH

    for script in (DEPLOY_SH, PREVIEW_SH):
        assert os.access(script, os.X_OK), f"{script} must be executable (git mode 100755)"


def test_a_script_that_cannot_start_ends_the_job_with_an_error(tmp_path):
    from scripts.previews import run_in_background

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
