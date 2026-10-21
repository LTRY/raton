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
    previews = parse_previews(f"31 9031 {'a' * 40} running\n7 9007 - exited\nnoise\n")

    assert previews == {
        31: Preview(31, 9031, "a" * 40, "running"),
        7: Preview(7, 9007, "-", "exited"),
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
        {5: Preview(5, 9005, "c" * 40, "running")},
        {},
        None,
    )

    assert "Une PR &lt;ouverte&gt;" in page
    assert 'action="/prs/31/up"' in page
    assert 'action="/prs/32/up"' not in page  # a fork never gets a deploy button
    assert 'action="/prs/5/down"' in page
    assert 'href="http://nas:9005/"' in page
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
